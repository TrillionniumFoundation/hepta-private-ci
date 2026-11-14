#!/usr/bin/env python3
"""Read-only exact-head verification runner for Hepta MemoryCell development.

This is NOT a production acceptance or CI authority. It never changes Git refs,
installs dependencies, selects trained artifacts, or promotes topology.
The pilot checks are a faithful *subset* of the six-stage evidence contract.
Run only against an authorized unified local checkout; missing source and queued
checks remain blockers, not successes.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class Check:
    stage: str
    name: str
    argv: tuple[str, ...]
    required_paths: tuple[str, ...] = ()
    cwd: str = "."
    timeout_s: int = 1200


def py_test(stage: str, file_pattern: str, timeout_s: int = 1200) -> Check:
    return Check(
        stage, f"Python: {file_pattern}",
        (sys.executable, "-m", "unittest", "discover", "-s", "qa/stem-bakeoff", "-p", file_pattern, "-v"),
        ("qa/stem-bakeoff/" + file_pattern,) if "*" not in file_pattern else ("qa/stem-bakeoff",),
        timeout_s=timeout_s,
    )


# All phase checks must run on one integrated source, not independent green PR heads.
CHECKS: tuple[Check, ...] = (
    Check("01-contract", "MemoryCell, Neuron and retrieval contracts",
          ("just", "test", "-p", "codex-hepta-cognitive-types", "-p", "codex-hepta-neuron", "-p", "codex-hepta-memory-retrieval", "--lib", "--locked", "--retries", "0"),
          ("codex-rs/hepta-memory-retrieval/src/memory_cell.rs",), timeout_s=3600),
    Check("01-persistence", "Current-owner checkpoint / Agentd integration",
          ("just", "test", "-p", "codex-hepta-memory", "-p", "codex-hepta-agentd", "--lib", "--locked", "--retries", "0"),
          ("codex-rs/hepta-memory/src/memory_cell_state_store.rs", "codex-rs/hepta-agentd/src/memory_cell_persistence.rs"), timeout_s=3600),
    py_test("02-organization", "test_memory_retrieval_probe.py"),
    py_test("03-real-learning", "test_cell_head_training.py"),
    py_test("03-real-learning", "test_procedure_replay.py"),
    py_test("03-real-learning", "test_procedure_replay_verify.py"),
    py_test("03-real-learning", "test_procedure_native_export.py"),
    py_test("04-routing", "test_cell_router_training.py"),
    py_test("05-evolution", "test_cell_evolution.py"),
    py_test("06-multimodal", "test_multimodal_bridge.py"),
    py_test("06-multimodal", "test_shared_student_training.py"),
    py_test("06-cross-process", "test_cell_process_inference.py"),
    py_test("06-scale", "test_scale_probe.py"),
    Check("07-format", "Repository-wide no-edit formatting", ("just", "fmt-check"), ("justfile",), timeout_s=1800),
    Check("07-architecture", "Canonical development document verifier",
          (sys.executable, "scripts/hepta-docs.py", "verify", "--profile", "development"),
          ("scripts/hepta-docs.py",), timeout_s=1200),
    Check("07-security", "Cargo advisory/license/source gate",
          ("cargo", "deny", "check"), ("codex-rs/Cargo.lock",), cwd="codex-rs", timeout_s=1800),
)

# These MUST be evaluated separately from the local unit/regression suite.
EXTERNAL_GATES = (
    "Exact same source/tree: blocking-ci, Architecture, V8, Linux/macOS/Windows Bazel and cargo-deny terminal success",
    "Frozen real Reader with independent strong RAG, source-family holdout and calibrated semantic citation adjudication",
    "Independent evaluation: three authenticated snapshots and two actually observed future calendar windows",
    "Current-source/tombstone and parameter lineage unlearning, crash/restart, backup/restore, cross-principal isolation",
    "Physical independent-host multi-node effect/failure tests (same-host Python IPC is insufficient)",
    "Measured end-to-end cost/quality superiority; negative task, router, split and shared-student results cannot be relabeled",
    "Independent operator decision, next-snapshot selection/rollback and FinalUse authority (no self-activation)",
)


def git(repo: Path, *args: str) -> str:
    p = subprocess.run(["git", *args], cwd=repo, text=True, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, check=True, timeout=25)
    return p.stdout.strip()


def tail(path: Path, max_lines: int = 20) -> list[str]:
    from collections import deque
    with path.open("r", encoding="utf-8", errors="replace") as f:
        return [line.rstrip("\n")[:600] for line in deque(f, maxlen=max_lines)]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for part in iter(lambda: f.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def run_one(check: Check, repo: Path, out: Path, expected_head: str, expected_status: str) -> dict:
    prefix = f"{check.stage}-{check.name.lower().replace(' ', '-')[:32]}"
    result = {"stage": check.stage, "name": check.name, "argv": list(check.argv),
              "cwd": check.cwd, "status": "BLOCKED", "head": expected_head, "duration_s": 0.0}
    missing = [str(p) for p in check.required_paths if not (repo / p).exists()]
    if missing:
        result["reason"] = "required checked-in source missing from this checkout"
        result["missing_paths"] = missing
        return result
    if shutil.which(check.argv[0]) is None:
        result["reason"] = f"required command unavailable: {check.argv[0]}"
        return result
    if git(repo, "rev-parse", "HEAD") != expected_head or git(repo, "status", "--porcelain") != expected_status:
        result["reason"] = "source HEAD/worktree drifted before check"
        return result
    logfile = out / f"{len(list(out.glob('*.log')))+1:02d}-{prefix}.log"
    started = time.monotonic()
    with logfile.open("wb") as stream:
        try:
            proc = subprocess.Popen(check.argv, cwd=repo / check.cwd,
                                    stdout=stream, stderr=subprocess.STDOUT,
                                    start_new_session=(os.name == "posix"))
            try:
                exit_code = proc.wait(timeout=check.timeout_s)
            except subprocess.TimeoutExpired:
                if os.name == "posix":
                    os.killpg(proc.pid, signal.SIGKILL)
                else:
                    proc.kill()
                proc.wait()
                exit_code = None
                result["reason"] = "deadline exceeded; process terminated"
            result["exit_code"] = exit_code
        except OSError as exc:
            result["reason"] = f"OS execution error: {type(exc).__name__}"
            result["exit_code"] = None
    result["duration_s"] = round(time.monotonic() - started, 3)
    result["log"] = str(logfile)
    result["log_sha256"] = sha256(logfile)
    result["tail"] = tail(logfile)
    if result.get("exit_code") is not None:
        result["status"] = "PASS" if result["exit_code"] == 0 else "FAIL"
    if git(repo, "rev-parse", "HEAD") != expected_head or git(repo, "status", "--porcelain") != expected_status:
        result["status"] = "BLOCKED"
        result["reason"] = "source HEAD/worktree drifted during execution"
    return result


def write_report(out: Path, report: dict) -> None:
    path = out / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Fail-closed Hepta six-stage local check runner (no Git mutations)")
    p.add_argument("--repo", type=Path, default=Path.cwd(), help="unified checkout directory")
    p.add_argument("--expected-head", default=None, help="optional exact 40-digit source HEAD pin")
    p.add_argument("--out", type=Path, default=None, help="report directory (prefer outside checkout)")
    p.add_argument("--run", action="store_true", help="execute; without this only prints the plan")
    p.add_argument("--allow-dirty", action="store_true", help="development-only; never qualifies a release")
    p.add_argument("--self-test", action="store_true", help="validate the script's check manifest")
    a = p.parse_args(argv)
    if a.self_test:
        groups = {x.stage.split("-")[0] for x in CHECKS}
        assert all(f"{n:02}" in groups for n in range(1, 8)), groups
        assert len({(x.stage,x.name) for x in CHECKS}) == len(CHECKS)
        assert all(x.argv and x.timeout_s > 0 and not x.argv[0].startswith("-") for x in CHECKS)
        assert len(EXTERNAL_GATES) >= 6
        print(f"Manifest integrity PASS: {len(CHECKS)} commands, {len(EXTERNAL_GATES)} external gates")
        return 0
    if not a.run:
        for x in CHECKS:
            print(f"{x.stage:18} {x.name:57} {' '.join(x.argv)}")
        print("\nEXTERNAL GATES: always OPEN until independently evidenced")
        for line in EXTERNAL_GATES: print("  - " + line)
        return 0

    repo = a.repo.resolve()
    out = a.out.resolve() if a.out else Path(tempfile.mkdtemp(prefix="hepta-memorycell-verify-"))
    out.mkdir(parents=True, exist_ok=True)
    report = {"schema": "hepta.memorycell.local-verification.v1",
              "started_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
              "checkout": str(repo), "results": [],
              "external_gates": [{"name": gate, "status": "OPEN_UNVERIFIED"} for gate in EXTERNAL_GATES],
              "production_accepted": False, "all_blockers_closed": False}
    try:
        root = Path(git(repo, "rev-parse", "--show-toplevel")).resolve()
        if root != repo or not (repo / "justfile").exists() or not (repo / "codex-rs").exists():
            raise ValueError("expected Hepta Git root with justfile/codex-rs")
        head = git(repo, "rev-parse", "HEAD")
        if a.expected_head and head != a.expected_head:
            raise ValueError("exact HEAD does not equal --expected-head")
        source_status = git(repo, "status", "--porcelain")
        dirty = bool(source_status)
        report.update(source_head=head, source_tree=git(repo, "rev-parse", "HEAD^{tree}"), dirty=dirty)
        if dirty and not a.allow_dirty:
            raise ValueError("uncommitted/untracked changes; require a clean checkout for evidence")
        if not shutil.which("git"):
            raise ValueError("git unavailable")
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        report["fatal_preflight"] = str(exc)
        report["completed_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        write_report(out, report)
        print(f"BLOCKED: {exc}\nReport: {out / 'report.json'}", file=sys.stderr)
        return 2
    print(f"Running {len(CHECKS)} read-only checks on {head}; receipts: {out}", flush=True)
    for check in CHECKS:
        result = run_one(check, repo, out, head, source_status)
        report["results"].append(result)
        write_report(out, report)
        print(f"[{result['status']}] {result['stage']} {result['name']}", flush=True)
        if result.get("reason") == "source HEAD/worktree drifted during execution":
            break
    report["completed_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    report["local_checks_passed"] = (not dirty and bool(report["results"]) and len(report["results"]) == len(CHECKS) and all(x["status"] == "PASS" for x in report["results"]))
    # External acceptance MUST NEVER be inferred from an executable unit-test suite.
    write_report(out, report)
    print(f"Local checks passed: {report['local_checks_passed']}; ALL BLOCKERS CLOSED: False\nReport: {out / 'report.json'}")
    return 0 if report["local_checks_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
