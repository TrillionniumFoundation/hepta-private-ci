#!/usr/bin/env python3
"""Fail-closed, non-authorizing E0-E4 experiment provenance and host measurements.

This is NOT a Cell trainer, an outcome observer, or a promotion evaluator.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

PLAN_SCHEMA = "hepta.neuron.experiment-plan.v2"
RUN_SCHEMA = "hepta.neuron.experiment-run.v3"
ARMS = {
    "E0": ("no_change",),
    "E1": ("multi_head", "fixed_moe", "dynamic_moe", "cell_graph"),
    "E2": ("no_change", "continue_training", "wider_head", "split", "merge", "distill"),
    "E3": ("fixed_circuit", "adaptive_circuit", "cell_ablation"),
    "E4": ("64", "256", "1024", "4096"),
}
SHARED = ("encoder", "tokenizer", "dataset", "objective", "runtime")
E0_MODEL = ("model_manifest", "preprocessor", "quantization", "normalizer",
            "calibration", "device_manifest", "license_sbom")
MAX_LOG_BYTES = 50_000_000
MAX_JSON_BYTES = 8_000_000
MAX_REPETITIONS = 1000
PERFORMANCE_ENV = (
    "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "RAYON_NUM_THREADS",
    "CUDA_VISIBLE_DEVICES", "CUDA_LAUNCH_BLOCKING", "PYTORCH_CUDA_ALLOC_CONF",
    "NUMEXPR_NUM_THREADS", "TOKENIZERS_PARALLELISM", "HEPTA_NEURON_THREADS",
)


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


def performance_environment() -> dict[str, str | None]:
    return {key: os.environ.get(key) for key in PERFORMANCE_ENV}


def load_json(path: Path) -> dict:
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_JSON_BYTES,
            "missing, linked or oversized JSON evidence")
    obj = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(obj, dict), "expected JSON object")
    return obj


def file_binding(path: str) -> dict[str, str]:
    p = Path(path).resolve(strict=True)
    # Local-only plan: preserve paths so subsequent runs verify actual bytes, not claimed digests.
    return {"path": str(p), "sha256": sha256_file(p)}


def bind_command(command: list[str], repo: Path) -> dict:
    require(isinstance(command, list) and command and all(isinstance(c, str) and c for c in command), "invalid command manifest")
    executable = Path(command[0])
    if not executable.is_absolute() and "/" in command[0]:
        executable = repo / executable
    elif "/" not in command[0]:
        found = shutil.which(command[0])
        require(found is not None, "executable is not on PATH")
        executable = Path(found)
    executable = executable.resolve(strict=True)
    arg_files: dict[str, dict[str, str]] = {}
    for index, arg in enumerate(command[1:], start=1):
        # Preserve command-list dependencies that exist on disk at freeze time.
        # Positional and --option=value file arguments are both bound.
        candidate = arg.split("=", 1)[1] if arg.startswith("--") and "=" in arg else arg
        if candidate.startswith("-") or "\n" in candidate:
            continue
        resolved = Path(candidate)
        if not resolved.is_absolute():
            resolved = repo / resolved
        if resolved.is_file():
            arg_files[str(index)] = file_binding(str(resolved))
    return {"argv": command, "executable": file_binding(str(executable)),
            "argument_files": arg_files}


def freeze(repo: Path, manifest: Path, stage: str, output: Path, repetitions: int = 1) -> None:
    require(stage in ARMS, "unknown stage")
    require(type(repetitions) is int and 1 <= repetitions <= MAX_REPETITIONS, "invalid frozen repetitions")
    require(not output.exists(), "plan already exists; refusing to overwrite frozen identity")
    spec = load_json(manifest)
    expected_fields = {"shared", "arms", "commands"} | ({"e0_model"} if stage == "E0" else set())
    require(set(spec) == expected_fields, "missing E0 model/commands or unknown manifest fields")
    if stage == "E0":
        require(isinstance(spec["e0_model"], dict) and set(spec["e0_model"]) == set(E0_MODEL), "incomplete E0 model identity")
        require(all(isinstance(value, str) and value for value in spec["e0_model"].values()), "invalid E0 model files")
    require(isinstance(spec["shared"], dict) and set(spec["shared"]) == set(SHARED), "missing common artifacts")
    require(isinstance(spec["arms"], dict) and set(spec["arms"]) == set(ARMS[stage]), "incomplete experiment arms")
    require(isinstance(spec["commands"], dict) and set(spec["commands"]) == set(ARMS[stage]), "incomplete frozen command matrix")
    require(all(isinstance(v, str) and v for v in [*spec["shared"].values(), *spec["arms"].values()]), "paths must be nonempty")
    plan = {
        "schema": PLAN_SCHEMA, "stage": stage, "source": source(repo), "host": host(),
        "performance_environment": performance_environment(),
        "shared": {key: file_binding(spec["shared"][key]) for key in SHARED},
        "arms": {key: file_binding(spec["arms"][key]) for key in ARMS[stage]},
        "commands": {key: bind_command(spec["commands"][key], repo) for key in ARMS[stage]},
        "e0_model": ({key: file_binding(spec["e0_model"][key]) for key in E0_MODEL} if stage == "E0" else None),
        "repetitions": repetitions, "created_unix_ns": time.time_ns(),
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
    require(type(plan.get("repetitions")) is int and 1 <= plan["repetitions"] <= MAX_REPETITIONS, "plan repetitions invalid")
    require(plan.get("authority") == "none" and plan.get("qualification") == "not_established", "plan asserts authority")
    require(plan.get("source") == source(repo), "source commit/tree drift")
    require(plan.get("host") == host(), "different target host/environment")
    require(plan.get("performance_environment") == performance_environment(), "performance environment drift")
    require(isinstance(plan.get("shared"), dict) and isinstance(plan.get("arms"), dict) and
            set(plan["shared"]) == set(SHARED) and set(plan["arms"]) == set(ARMS[stage]),
            "plan is missing arms/artifacts")
    require(isinstance(plan.get("commands"), dict) and set(plan["commands"]) == set(ARMS[stage]) and
            all(isinstance(x, dict) for x in plan["commands"].values()), "plan frozen commands missing")
    require((isinstance(plan.get("e0_model"), dict) and set(plan["e0_model"]) == set(E0_MODEL))
            if stage == "E0" else plan.get("e0_model") is None, "plan E0 model binding missing")
    for binding in [*plan["shared"].values(), *plan["arms"].values(),
                    *(plan["e0_model"].values() if stage == "E0" else []),
                    *(x.get("executable") for x in plan["commands"].values())]:
        require(isinstance(binding, dict) and set(binding) == {"path", "sha256"}, "invalid artifact binding")
        require(sha256_file(Path(binding["path"])) == binding["sha256"], "artifact byte drift")
    for arm, bound in plan["commands"].items():
        require(isinstance(bound, dict) and set(bound) == {"argv", "executable", "argument_files"}, "invalid command binding")
        require(isinstance(bound["argument_files"], dict), "invalid file argument bindings")
        require(bind_command(bound["argv"], repo) == bound, f"frozen command drift: {arm}")
    return plan


def sample_linux_process_group(pgid: int) -> tuple[int, int]:
    """A non-authoritative instantaneous RSS lower-bound from Linux procfs."""
    if not sys.platform.startswith("linux") or not Path("/proc").is_dir():
        return 0, 0
    pagesize_kib = os.sysconf("SC_PAGE_SIZE") // 1024
    rss_kib = 0
    visible = 0
    for entry in Path("/proc").iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            stat = (entry / "stat").read_text(encoding="utf-8")
            # Field 2 is a parenthesized name; whitespace inside it is legal.
            fields = stat.rsplit(") ", 1)[1].split()
            if int(fields[2]) != pgid:  # field 5: process group ID
                continue
            resident_pages = int((entry / "statm").read_text().split()[1])
            rss_kib += max(0, resident_pages) * pagesize_kib
            visible += 1
        except (OSError, IndexError, ValueError):
            # Vanishing / inaccessible processes are unmeasured, not zero RSS.
            continue
    return rss_kib, visible


def run(repo: Path, plan_file: Path, arm: str, output: Path, timeout: float,
        command: list[str], trial: int = 0, sample_group_rss: bool = False) -> None:
    plan = verify_plan(plan_file, repo)
    require(arm in ARMS[plan["stage"]], "unregistered arm")
    require(type(trial) is int and 0 <= trial < plan["repetitions"], "unregistered trial")
    require(command and command[0] != "--", "missing executable")
    require(0 < timeout <= 3600, "invalid bounded timeout")
    require(not output.exists(), "run receipt already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    stdout_path = output.with_suffix(output.suffix + ".stdout")
    stderr_path = output.with_suffix(output.suffix + ".stderr")
    require(not stdout_path.exists() and not stderr_path.exists(), "run logs already exist")
    frozen = plan["commands"][arm]
    require(command == frozen["argv"], "attempted unfrozen command")
    executable = Path(frozen["executable"]["path"])
    executable_digest = sha256_file(executable)
    require(executable_digest == frozen["executable"]["sha256"], "frozen executable drift")
    t0 = time.monotonic_ns()
    status = "completed"
    return_code = None
    sampled_group_peak = 0
    group_samples = 0
    sampling_ns = 0
    with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
        child_environment = os.environ.copy()
        child_environment["HEPTA_NEURON_EXPERIMENT_TRIAL"] = str(trial)
        # Never re-resolve argv[0] through a mutable PATH after frozen identity checks.
        exact_command = [str(executable), *command[1:]]
        process = subprocess.Popen(exact_command, cwd=repo, stdout=stdout, stderr=stderr,
                                   start_new_session=True, env=child_environment)
        deadline = time.monotonic() + timeout
        next_group_sample = 0.0
        while True:
            if sample_group_rss and sys.platform.startswith("linux") and time.monotonic() >= next_group_sample:
                sample_started = time.monotonic_ns()
                current_rss, visible = sample_linux_process_group(process.pid)
                sampling_ns += time.monotonic_ns() - sample_started
                if visible:
                    group_samples += 1
                    sampled_group_peak = max(sampled_group_peak, current_rss)
                next_group_sample = time.monotonic() + 0.1
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
    # The direct child can exit successfully while a same-session helper still
    # writes evidence or executes model code. A complete run must settle its
    # isolated process group, not just the first PID.
    if status == "completed":
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            pass
        else:
            status = "unsettled_descendants"
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    try:
        executable_after = sha256_file(executable)
    except (OSError, EvidenceError):
        executable_after = None
    if executable_after != executable_digest:
        status = "executable_drift"
    # Reopen and rehash the ENTIRE frozen source/artifact/argument inventory
    # after the executable has finished. Checking only argv[0] leaves an
    # ordinary input mutation during execution undetected. This remains a
    # before/after check, not an attestation of bytes actually consumed.
    postrun_binding_verified = False
    try:
        verify_plan(plan_file, repo)
        postrun_binding_verified = True
    except (EvidenceError, OSError, subprocess.CalledProcessError, ValueError):
        if status == "completed":
            status = "postrun_binding_drift"
    # Per-direct-child wait4 resource usage. Descendant CPU/RSS and GPU remain unmeasured.
    rss = usage.ru_maxrss
    if sys.platform == "darwin":
        rss //= 1024
    receipt = {
        "schema": RUN_SCHEMA, "stage": plan["stage"], "arm": arm, "trial": trial,
        "plan_digest": plan["plan_digest"], "source": plan["source"], "host": plan["host"],
        "performance_environment": plan["performance_environment"],
        "artifact_sha256": plan["arms"][arm]["sha256"],
        "command_sha256": digest(command), "executable_path": str(executable),
        "executable_sha256": executable_digest, "status": status, "exit_code": return_code,
        "postrun_binding_verified": postrun_binding_verified,
        "elapsed_wall_ns": elapsed,
        "child_user_cpu_ns": int(max(0, usage.ru_utime) * 1e9),
        "child_system_cpu_ns": int(max(0, usage.ru_stime) * 1e9),
        "child_peak_rss_kib": int(rss), "rss_scope": "direct_child_high_water_not_process_tree",
        "sampled_process_group_peak_rss_kib": sampled_group_peak if group_samples else None,
        "sampled_process_group_observations": group_samples,
        "process_group_rss_scope": ("linux_procfs_sampled_lower_bound" if group_samples else "not_measured"),
        "sampler_overhead_ns": sampling_ns,
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
    found: dict[str, int] = {arm: 0 for arm in ARMS[plan["stage"]]}
    observed_slots: set[tuple[str, int]] = set()
    per_arm_commands: dict[str, str] = {}
    per_arm_executables: dict[str, str] = {}
    wall_by_arm: dict[str, list[int]] = {arm: [] for arm in ARMS[plan["stage"]]}
    for path in receipt_paths:
        rec = load_json(path)
        checksum = rec.pop("receipt_digest", None)
        require(isinstance(checksum, str) and digest(rec) == checksum, "receipt digest mismatch")
        rec["receipt_digest"] = checksum
        require(rec.get("schema") == RUN_SCHEMA, "invalid receipt schema")
        require(rec.get("plan_digest") == plan["plan_digest"] and rec.get("source") == plan["source"] and rec.get("host") == plan["host"], "receipt plan/source/host mismatch")
        require(rec.get("performance_environment") == plan["performance_environment"], "receipt performance environment mismatch")
        arm = rec.get("arm")
        require(rec.get("stage") == plan["stage"] and arm in ARMS[plan["stage"]], "unregistered receipt arm")
        trial = rec.get("trial")
        require(type(trial) is int and 0 <= trial < plan["repetitions"], "unregistered receipt trial")
        slot = arm, trial
        require(slot not in observed_slots, "duplicate arm/trial receipt")
        observed_slots.add(slot)
        require(rec.get("artifact_sha256") == plan["arms"][arm]["sha256"], "receipt artifact mismatch")
        require(rec.get("status") == "completed" and rec.get("exit_code") == 0, "incomplete/failed model execution")
        require(rec.get("postrun_binding_verified") is True, "postrun source/artifacts were not verified")
        require(isinstance(rec.get("executable_path"), str) and sha256_file(Path(rec["executable_path"])) == rec.get("executable_sha256"), "executable byte drift")
        require(rec["executable_path"] == plan["commands"][arm]["executable"]["path"] and
                rec["executable_sha256"] == plan["commands"][arm]["executable"]["sha256"] and
                rec.get("command_sha256") == digest(plan["commands"][arm]["argv"]), "receipt frozen command mismatch")
        cmd_hash = rec.get("command_sha256")
        executable_hash = rec.get("executable_sha256")
        require(isinstance(cmd_hash, str) and len(cmd_hash) == 64, "missing command identity")
        if arm in per_arm_commands:
            require(per_arm_commands[arm] == cmd_hash and per_arm_executables[arm] == executable_hash, "per-arm command/executable drift")
        else:
            per_arm_commands[arm] = cmd_hash
            per_arm_executables[arm] = executable_hash
        require(rec.get("authority") == "none" and rec.get("qualification") == "not_established" and rec.get("outcomes") == "not_independently_observed", "receipt invents qualification")
        require(type(rec.get("elapsed_wall_ns")) is int and rec["elapsed_wall_ns"] > 0, "missing measured wall time")
        require(type(rec.get("child_peak_rss_kib")) is int and rec["child_peak_rss_kib"] > 0, "missing RSS observation")
        require(not rec.get("outputs_oversized") and rec.get("stdout_sha256") and rec.get("stderr_sha256"), "unbound/oversized logs")
        for kind in ("stdout", "stderr"):
            log = path.with_suffix(path.suffix + "." + kind)
            require(log.is_file() and not log.is_symlink() and log.stat().st_size <= MAX_LOG_BYTES, "missing/oversized raw log")
            require(log.stat().st_size == rec[kind + "_bytes"], "raw log size drift")
            require(hashlib.sha256(log.read_bytes()).hexdigest() == rec[kind + "_sha256"], "raw log digest drift")
        found[arm] += 1
        wall_by_arm[arm].append(rec["elapsed_wall_ns"])
    missing_slots = [(arm, trial) for arm in ARMS[plan["stage"]]
                     for trial in range(plan["repetitions"])
                     if (arm, trial) not in observed_slots]
    def nearest_rank(xs: list[int], p: float, minimum_n: int) -> int | None:
        if len(xs) < minimum_n:
            return None
        xs = sorted(xs)
        return xs[math.ceil(len(xs) * p) - 1]

    wall_stats = {
        arm: {
            "unit": "ns", "scope": "whole_child_process_including_startup",
            "n": len(wall_by_arm[arm]),
            "p50": nearest_rank(wall_by_arm[arm], 0.50, 3),
            "p95": nearest_rank(wall_by_arm[arm], 0.95, 20),
            "p99": nearest_rank(wall_by_arm[arm], 0.99, 100),
        }
        for arm in ARMS[plan["stage"]]
    }
    return {"schema": "hepta.neuron.experiment-audit.v3", "stage": plan["stage"],
            "plan_digest": plan["plan_digest"], "frozen_repetitions_per_arm": plan["repetitions"],
            "executed_arms": {arm: n for arm, n in found.items() if n},
            "missing_arms": sorted(arm for arm, n in found.items() if not n),
            "missing_slots": [{"arm": a, "trial": t} for a, t in missing_slots],
            "execution_matrix_complete": not missing_slots,
            "whole_process_wall_time_only": wall_stats,
            "e0_model_manifest_and_auxiliary_files_frozen": plan["stage"] == "E0",
            "model_and_dataset_consumption": "not_independently_verified",
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
    p.add_argument("--repetitions", type=int, default=1)
    p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("run")
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--arm", required=True)
    p.add_argument("--trial", type=int, default=0)
    p.add_argument("--sample-group-rss", action="store_true")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--timeout", type=float, default=120)
    p.add_argument("command", nargs=argparse.REMAINDER)
    p = sub.add_parser("audit")
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--receipts", nargs="+", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.op == "freeze":
            freeze(args.repo, args.manifest, args.stage, args.out, args.repetitions)
        elif args.op == "run":
            command = args.command[1:] if args.command[:1] == ["--"] else args.command
            run(args.repo, args.plan, args.arm, args.out, args.timeout, command, args.trial, args.sample_group_rss)
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
