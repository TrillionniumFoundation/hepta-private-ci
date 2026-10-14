#!/usr/bin/env python3
"""Fail-closed, non-authorizing E0-E4 experiment provenance and host measurements.

This is NOT a Cell trainer, an outcome observer, or a promotion evaluator.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import resource
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

PLAN_SCHEMA = "hepta.neuron.experiment-plan.v1"
RUN_SCHEMA = "hepta.neuron.experiment-run.v1"
ARMS = {
    "E0": ("no_change",),
    "E1": ("multi_head", "fixed_moe", "dynamic_moe", "cell_graph"),
    "E2": ("no_change", "continue_training", "wider_head", "split", "merge", "distill"),
    "E3": ("fixed_circuit", "adaptive_circuit", "cell_ablation"),
    "E4": ("64", "256", "1024", "4096"),
}
SHARED = ("encoder", "tokenizer", "dataset", "objective", "runtime")
MAX_LOG_BYTES = 50_000_000


class EvidenceError(ValueError):
    pass


def require(condition: bool, why: str) -> None:
    if not condition:
        raise EvidenceError(why)


def canonical(obj: object) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(obj: object) -> str:
    return hashlib.sha256(canonical(obj)).hexdigest()


def sha256_file(path: Path) -> str:
    require(path.is_file() and not path.is_symlink(), f"missing/linked source file: {path}")
    require(path.stat().st_size > 0, f"empty source file: {path}")
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)
    return r.stdout.strip()


def source(repo: Path) -> dict[str, str]:
    require(not git(repo, "status", "--porcelain", "--untracked-files=no"), "tracked source is dirty")
    commit = git(repo, "rev-parse", "HEAD")
    tree = git(repo, "rev-parse", "HEAD^{tree}")
    require(len(commit) == 40 and len(tree) == 40, "invalid Git source identity")
    return {"commit": commit, "tree": tree}


def host() -> dict[str, str]:
    # Hashed host identity prevents the provenance file exposing an operator hostname.
    name = platform.node().encode("utf-8")
    return {"host_sha256": hashlib.sha256(name).hexdigest(),
            "os": platform.system(), "arch": platform.machine(),
            "cpu_count": os.cpu_count(), "python": platform.python_version()}


def load_json(path: Path) -> dict:
    obj = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(obj, dict), "expected JSON object")
    return obj


def file_binding(path: str) -> dict[str, str]:
    p = Path(path).resolve(strict=True)
    # Local-only plan: preserve paths so subsequent runs verify actual bytes, not claimed digests.
    return {"path": str(p), "sha256": sha256_file(p)}


def freeze(repo: Path, manifest: Path, stage: str, output: Path) -> None:
    require(stage in ARMS, "unknown stage")
    require(not output.exists(), "plan already exists; refusing to overwrite frozen identity")
    spec = load_json(manifest)
    require(set(spec) == {"shared", "arms"}, "unexpected manifest fields")
    require(isinstance(spec["shared"], dict) and set(spec["shared"]) == set(SHARED), "missing common artifacts")
    require(isinstance(spec["arms"], dict) and set(spec["arms"]) == set(ARMS[stage]), "incomplete experiment arms")
    require(all(isinstance(v, str) and v for v in [*spec["shared"].values(), *spec["arms"].values()]), "paths must be nonempty")
    plan = {
        "schema": PLAN_SCHEMA, "stage": stage, "source": source(repo), "host": host(),
        "shared": {key: file_binding(spec["shared"][key]) for key in SHARED},
        "arms": {key: file_binding(spec["arms"][key]) for key in ARMS[stage]},
        "created_unix_ns": time.time_ns(),
        "authority": "none", "qualification": "not_established",
    }
    plan["plan_digest"] = digest(plan)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as f:
        json.dump(plan, f, sort_keys=True, indent=2)
        f.write("\n")


def verify_plan(path: Path, repo: Path) -> dict:
    plan = load_json(path)
    claimed = plan.pop("plan_digest", None)
    require(isinstance(claimed, str) and digest(plan) == claimed, "plan digest mismatch")
    plan["plan_digest"] = claimed
    stage = plan.get("stage")
    require(plan.get("schema") == PLAN_SCHEMA and stage in ARMS, "plan schema/stage invalid")
    require(plan.get("authority") == "none" and plan.get("qualification") == "not_established", "plan asserts authority")
    require(plan.get("source") == source(repo), "source commit/tree drift")
    require(plan.get("host") == host(), "different target host/environment")
    require(set(plan.get("shared", {})) == set(SHARED) and set(plan.get("arms", {})) == set(ARMS[stage]), "plan is missing arms/artifacts")
    for binding in [*plan["shared"].values(), *plan["arms"].values()]:
        require(isinstance(binding, dict) and set(binding) == {"path", "sha256"}, "invalid artifact binding")
        require(sha256_file(Path(binding["path"])) == binding["sha256"], "artifact byte drift")
    return plan


def run(repo: Path, plan_file: Path, arm: str, output: Path, timeout: float, command: list[str]) -> None:
    plan = verify_plan(plan_file, repo)
    require(arm in ARMS[plan["stage"]], "unregistered arm")
    require(command and command[0] != "--", "missing executable")
    require(0 < timeout <= 3600, "invalid bounded timeout")
    require(not output.exists(), "run receipt already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    stdout_path = output.with_suffix(output.suffix + ".stdout")
    stderr_path = output.with_suffix(output.suffix + ".stderr")
    require(not stdout_path.exists() and not stderr_path.exists(), "run logs already exist")
    executable = Path(command[0])
    if not executable.is_absolute() and "/" in command[0]:
        executable = repo / executable
    elif "/" not in command[0]:
        found = shutil.which(command[0])
        require(found is not None, "executable is not on PATH")
        executable = Path(found)
    executable = executable.resolve(strict=True)
    executable_digest = sha256_file(executable)
    t0 = time.monotonic_ns()
    status = "completed"
    return_code = None
    with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
        process = subprocess.Popen(command, cwd=repo, stdout=stdout, stderr=stderr, start_new_session=True)
        deadline = time.monotonic() + timeout
        while True:
            waited, wait_status, usage = os.wait4(process.pid, os.WNOHANG)
            if waited == process.pid:
                return_code = os.waitstatus_to_exitcode(wait_status)
                process.returncode = return_code
                if return_code != 0:
                    status = "failed"
                break
            if time.monotonic() >= deadline or stdout_path.stat().st_size > MAX_LOG_BYTES or stderr_path.stat().st_size > MAX_LOG_BYTES:
                status = "timed_out" if time.monotonic() >= deadline else "output_limit"
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                _, wait_status, usage = os.wait4(process.pid, 0)
                return_code = os.waitstatus_to_exitcode(wait_status)
                process.returncode = return_code
                break
            time.sleep(min(.02, max(.001, deadline - time.monotonic())))
    elapsed = time.monotonic_ns() - t0
    # Per-direct-child wait4 resource usage. Descendant CPU/RSS and GPU remain unmeasured.
    rss = usage.ru_maxrss
    if sys.platform == "darwin":
        rss //= 1024
    receipt = {
        "schema": RUN_SCHEMA, "stage": plan["stage"], "arm": arm,
        "plan_digest": plan["plan_digest"], "source": plan["source"], "host": plan["host"],
        "artifact_sha256": plan["arms"][arm]["sha256"],
        "command_sha256": digest(command), "executable_path": str(executable),
        "executable_sha256": executable_digest, "status": status, "exit_code": return_code,
        "elapsed_wall_ns": elapsed,
        "child_user_cpu_ns": int(max(0, usage.ru_utime) * 1e9),
        "child_system_cpu_ns": int(max(0, usage.ru_stime) * 1e9),
        "child_peak_rss_kib": int(rss), "rss_scope": "direct_child_high_water_not_process_tree",
        "gpu_peak_bytes": None, "gpu_status": "not_measured",
        "stdout_sha256": hashlib.sha256(stdout_path.read_bytes()).hexdigest() if stdout_path.stat().st_size <= MAX_LOG_BYTES else None,
        "stderr_sha256": hashlib.sha256(stderr_path.read_bytes()).hexdigest() if stderr_path.stat().st_size <= MAX_LOG_BYTES else None,
        "stdout_bytes": stdout_path.stat().st_size, "stderr_bytes": stderr_path.stat().st_size,
        "outputs_oversized": stdout_path.stat().st_size > MAX_LOG_BYTES or stderr_path.stat().st_size > MAX_LOG_BYTES,
        "outcomes": "not_independently_observed", "authority": "none", "qualification": "not_established",
    }
    receipt["receipt_digest"] = digest(receipt)
    with output.open("x", encoding="utf-8") as f:
        json.dump(receipt, f, sort_keys=True, indent=2)
        f.write("\n")
    if status != "completed" or receipt["outputs_oversized"]:
        raise EvidenceError(f"run {status}; inspect bounded logs and receipt")


def audit(plan_file: Path, repo: Path, receipt_paths: list[Path]) -> dict:
    plan = verify_plan(plan_file, repo)
    found: dict[str, int] = {}
    for path in receipt_paths:
        rec = load_json(path)
        checksum = rec.pop("receipt_digest", None)
        require(isinstance(checksum, str) and digest(rec) == checksum, "receipt digest mismatch")
        rec["receipt_digest"] = checksum
        require(rec.get("schema") == RUN_SCHEMA, "invalid receipt schema")
        require(rec.get("plan_digest") == plan["plan_digest"] and rec.get("source") == plan["source"] and rec.get("host") == plan["host"], "receipt plan/source/host mismatch")
        arm = rec.get("arm")
        require(rec.get("stage") == plan["stage"] and arm in ARMS[plan["stage"]], "unregistered receipt arm")
        require(rec.get("artifact_sha256") == plan["arms"][arm]["sha256"], "receipt artifact mismatch")
        require(rec.get("status") == "completed" and rec.get("exit_code") == 0, "incomplete/failed model execution")
        require(isinstance(rec.get("executable_path"), str) and sha256_file(Path(rec["executable_path"])) == rec.get("executable_sha256"), "executable byte drift")
        require(rec.get("authority") == "none" and rec.get("qualification") == "not_established" and rec.get("outcomes") == "not_independently_observed", "receipt invents qualification")
        require(type(rec.get("elapsed_wall_ns")) is int and rec["elapsed_wall_ns"] > 0, "missing measured wall time")
        require(type(rec.get("child_peak_rss_kib")) is int and rec["child_peak_rss_kib"] > 0, "missing RSS observation")
        require(not rec.get("outputs_oversized") and rec.get("stdout_sha256") and rec.get("stderr_sha256"), "unbound/oversized logs")
        for kind in ("stdout", "stderr"):
            log = path.with_suffix(path.suffix + "." + kind)
            require(log.is_file() and not log.is_symlink() and log.stat().st_size <= MAX_LOG_BYTES, "missing/oversized raw log")
            require(log.stat().st_size == rec[kind + "_bytes"], "raw log size drift")
            require(hashlib.sha256(log.read_bytes()).hexdigest() == rec[kind + "_sha256"], "raw log digest drift")
        found[arm] = found.get(arm, 0) + 1
    missing = sorted(set(ARMS[plan["stage"]]) - set(found))
    return {"schema": "hepta.neuron.experiment-audit.v1", "stage": plan["stage"],
            "plan_digest": plan["plan_digest"], "executed_arms": found, "missing_arms": missing,
            "execution_matrix_complete": not missing,
            "fair_budget_and_parameter_comparison": "not_evaluated",
            "external_task_utility": "not_independently_observed",
            "longitudinal_efficacy": "not_established",
            "device_gpu_and_full_process_rss": "not_measured",
            "cell_split_approval": False, "release_authority": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    sub = parser.add_subparsers(dest="op", required=True)
    p = sub.add_parser("freeze")
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--stage", choices=sorted(ARMS), required=True)
    p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("run")
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--arm", required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--timeout", type=float, default=120)
    p.add_argument("command", nargs=argparse.REMAINDER)
    p = sub.add_parser("audit")
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--receipts", nargs="+", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.op == "freeze":
            freeze(args.repo, args.manifest, args.stage, args.out)
        elif args.op == "run":
            command = args.command[1:] if args.command[:1] == ["--"] else args.command
            run(args.repo, args.plan, args.arm, args.out, args.timeout, command)
        else:
            result = audit(args.plan, args.repo, args.receipts)
            print(json.dumps(result, sort_keys=True))
            if not result["execution_matrix_complete"]:
                return 2
        return 0
    except (EvidenceError, OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"FAIL_HEPTA_NEURON_EXPERIMENT: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
