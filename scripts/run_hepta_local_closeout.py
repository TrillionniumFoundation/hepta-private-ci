#!/usr/bin/env python3
"""Non-deploying local Hepta P0..P6 acceptance runner.

Runs source/build/unit checks on exact local worktrees and emits immutable-ish
machine-readable results. It NEVER treats a passing test as physical or
independent future-window acceptance; P1..P6 need separate external evidence.
No network requests, background jobs, production effects or Git writes.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import signal
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any

STAGES = {
    "P0": {
        "required": [("hepta", "codex-rs/hepta-types/src/execution_contract.rs"),
                     ("hepta", "qa/meta-network-scale/check_cell_codex_boundary.py")],
        "checks": [
            ("hepta", "codex-rs", ["cargo", "metadata", "--locked", "--format-version", "1", "--no-deps"]),
            ("hepta", "codex-rs", ["cargo", "fmt", "--all", "--", "--check"]),
            ("hepta", "codex-rs", ["cargo", "test", "--locked", "-p", "codex-hepta-types", "-p", "codex-hepta-codex-adapter"]),
            ("hepta", "codex-rs", ["cargo", "clippy", "--locked", "-p", "codex-hepta-types", "-p", "codex-hepta-codex-adapter", "--all-targets", "--", "-D", "warnings"]),
            ("hepta", ".", [sys.executable, "-m", "unittest", "qa/meta-network-scale/test_cell_codex_boundary.py"]),
        ],
        "external": "compiled transitive dependency and exact-head/merge CI acceptance",
    },
    "P1": {
        "required": [("hepta", "codex-rs/hepta-runtime/src/topology_execution.rs"),
                     ("hepta", "codex-rs/hepta-plasticity/src/topology_governance.rs")],
        "checks": [("hepta", "codex-rs", ["cargo", "test", "--locked", "-p", "codex-hepta-runtime", "-p", "codex-hepta-plasticity", "-p", "codex-hepta-operator-acceptance", "-p", "codex-hepta-supervisor"])],
        "external": "signed real Artifact CAS, state migration, CNS cutover, old-generation fence, ledger, power-loss recovery",
    },
    "P2": {
        "required": [("hepta", "codex-rs/hepta-infer-core/src/neuron_feature.rs"),
                     ("hepta", "codex-rs/hepta-neuron/src/runtime.rs")],
        "checks": [("hepta", "codex-rs", ["cargo", "test", "--locked", "-p", "codex-hepta-infer-core", "-p", "codex-hepta-infer-worker-host", "-p", "codex-hepta-neuron"])],
        "external": "pinned learned encoder weights/tokenizer, real train/heldout inference, backend batch, zero-delta parity",
    },
    "P3": {
        "required": [("runtime", "src/lib.rs"),
                     ("runtime", "tests/native_library_boundary.rs"),
                     ("hepta", "codex-rs/hepta-types/src/execution_contract.rs")],
        "checks": [
            ("runtime", ".", ["cargo", "fmt", "--all", "--", "--check"]),
            ("runtime", ".", ["cargo", "check", "--locked", "--all-targets"]),
            ("runtime", ".", ["cargo", "test", "--locked", "--all-targets"]),
            ("runtime", ".", ["cargo", "clippy", "--locked", "--all-targets", "--", "-D", "warnings"]),
            ("runtime", ".", ["cargo", "build", "--locked", "--release"]),
            ("hepta", "codex-rs", ["cargo", "test", "--locked", "-p", "codex-hepta-operations", "-p", "codex-hepta-codex-adapter"]),
        ],
        "external": "real native adapter + final-use consume-once + host policy + durable idempotency + terminal target readback",
    },
    "P4": {
        "required": [("hepta", "codex-rs/hepta-ndu/src/evaluator.rs"),
                     ("hepta", "codex-rs/hepta-intelligence-eval/src/self_evolution_selection.rs")],
        "checks": [("hepta", "codex-rs", ["cargo", "test", "--locked", "-p", "codex-hepta-ndu", "-p", "codex-hepta-intelligence-eval"])],
        "external": "preregistered heldout/no-change/fixed MoE controls, independent future-window utility, negative-transfer CI",
    },
    "P5": {
        "required": [("hepta", "qa/meta-network-scale/scale_matrix.py"),
                     ("hepta", "docs/learning/CELL_EXECUTION_BENCHMARK_MATRIX.json")],
        "checks": [("hepta", ".", [sys.executable, "-m", "unittest", "qa/meta-network-scale/test_scale_matrix.py"])],
        "external": "physical 1/8/64/256/1024/4096-cell 36-arm host-bound CPU/RSS/GPU/p95/p99/throughput/WAL/fault receipts",
    },
    "P6": {
        "required": [("hepta", "qa/meta-network-scale/p6_fallback_gate.py"),
                     ("hepta", "qa/meta-network-scale/test_p6_fallback_gate.py")],
        "checks": [("hepta", ".", [sys.executable, "-m", "unittest", "qa/meta-network-scale/test_p6_fallback_gate.py"])],
        "external": "real sandboxed Codex/native feature-equivalence cohort, distinct independent signatures, error and restart parity",
    },
}


def required_file_pin(root: Path, rel: str) -> dict[str, Any]:
    """Reject ignored/untracked and symlinked required files on a clean Git tree.

    'git status --porcelain' being empty is insufficient: Git ignores can hide
    untracked inputs, and a committed symlink can point to mutable external
    bytes. A source-only acceptance gate must not bless either as pinned.
    """
    relative = Path(rel)
    target = root / relative
    info: dict[str, Any] = {"present": target.is_file(), "pinned": False}
    if not info["present"]:
        info["reason"] = "MISSING_REGULAR_FILE"
        return info
    if relative.is_absolute() or ".." in relative.parts:
        info["reason"] = "UNSAFE_RELATIVE_PATH"
        return info
    cursor = root
    for component in relative.parts:
        cursor = cursor / component
        if cursor.is_symlink():
            info["reason"] = "SYMLINKED_SOURCE_PATH"
            return info
    try:
        tracked = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--stage", "--", rel],
            capture_output=True, text=True, check=True, timeout=10,
        ).stdout.splitlines()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        info["reason"] = "GIT_INDEX_UNAVAILABLE"
        return info
    entries = []
    for line in tracked:
        metadata, sep, path = line.partition("\t")
        fields = metadata.split()
        if sep and path == rel and len(fields) == 3:
            entries.append((fields[0], fields[2]))
    if entries != [("100644", "0")] and entries != [("100755", "0")]:
        info["reason"] = "NOT_A_SINGLE_TRACKED_REGULAR_FILE"
        return info
    info["pinned"] = True
    info["reason"] = "TRACKED_REGULAR_FILE"
    return info


def git_snapshot(path: Path) -> dict[str, Any]:
    if not path.is_dir():
        return {"usable": False, "reason": "repository directory not mounted", "path": str(path)}

    def cmd(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(path), *args], capture_output=True, text=True,
            check=True, timeout=10,
        ).stdout.strip()

    try:
        # Git's linked worktrees use a .git *file*, not a directory. Verify the
        # canonical top level instead of testing a filesystem suffix.
        if cmd("rev-parse", "--is-inside-work-tree") != "true":
            return {"usable": False, "path": str(path), "reason": "not a Git worktree"}
        if Path(cmd("rev-parse", "--show-toplevel")).resolve() != path.resolve():
            return {"usable": False, "path": str(path), "reason": "not a Git repository root"}
        rev = cmd("rev-parse", "--verify", "HEAD^{commit}")
        tree = cmd("rev-parse", "--verify", "HEAD^{tree}")
        state = cmd("status", "--porcelain=v1", "--untracked-files=all")
        return {"usable": True, "path": str(path), "commit": rev, "tree": tree,
                "clean": state == "", "dirty_paths": len(state.splitlines())}
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        return {"usable": False, "path": str(path), "reason": type(exc).__name__}


def run_check(argv: list[str], cwd: Path, timeout: int, log_path: Path) -> dict[str, Any]:
    if not shutil.which(argv[0]):
        return {"argv": argv, "status": "BLOCKED_TOOL_MISSING", "tool": argv[0]}
    if not cwd.is_dir():
        return {"argv": argv, "status": "BLOCKED_WORKDIR_MISSING"}
    start = time.monotonic()
    try:
        # Stream all Cargo/Bazel output to a private file; never hold a multi-GB
        # compilation log in Python heap. Use no shell or network orchestration.
        fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as out:
            out.write(("$ " + json.dumps(argv, ensure_ascii=False) + "\n").encode("utf-8"))
            out.flush()
            child = subprocess.Popen(argv, cwd=cwd, stdout=out, stderr=subprocess.STDOUT,
                                     env=os.environ.copy(), start_new_session=(os.name == "posix"))
            try:
                code = child.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                # Cargo can spawn rustc/test workers. Kill the process group on
                # POSIX rather than leaving hidden test processes running.
                try:
                    if os.name == "posix":
                        os.killpg(child.pid, signal.SIGKILL)
                    else:
                        child.kill()
                except ProcessLookupError:
                    pass
                child.wait()
                out.write(b"\nHEPTA_LOCAL_GATE: TIMEOUT; child process terminated\n")
                return {"argv": argv, "status": "BLOCKED_TIMEOUT", "seconds": round(time.monotonic() - start, 3), "log_path": str(log_path)}
            out.write(f"\nHEPTA_LOCAL_GATE_EXIT: {code}\n".encode("utf-8"))
            out.flush()
            os.fsync(out.fileno())
        digest = hashlib.sha256()
        with log_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return {"argv": argv, "status": "PASS_LOCAL" if code == 0 else "FAIL_LOCAL",
                "exit_code": code, "seconds": round(time.monotonic() - start, 3),
                "log_path": str(log_path), "log_sha256": digest.hexdigest()}
    except OSError as exc:
        return {"argv": argv, "status": "BLOCKED_SYSTEM", "error_type": type(exc).__name__}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hepta", required=True, type=Path, help="local hepta-private-ci checkout (not a GitHub URL)")
    parser.add_argument("--runtime", required=True, type=Path, help="local hepta-runtime checkout")
    parser.add_argument("--report-dir", type=Path, default=Path(tempfile.gettempdir()) / "hepta-local-closeout-results")
    parser.add_argument("--timeout-sec", type=int, default=900)
    parser.add_argument("--execute-checks", action="store_true", help="opt in to build/test; tests can write to local ephemeral test data; no production dispatch by this script")
    args = parser.parse_args()
    if args.timeout_sec < 1:
        parser.error("--timeout-sec must be positive")
    roots = {"hepta": args.hepta.resolve(), "runtime": args.runtime.resolve()}
    if args.report_dir.is_symlink():
        parser.error("report directory must not be a symlink")
    report_dir = args.report_dir.resolve()
    report_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name == "posix" and (report_dir.stat().st_mode & 0o077):
        parser.error("report directory must have private owner-only permissions")
    run_dir = report_dir / ("run-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    run_dir.mkdir(mode=0o700)
    report: dict[str, Any] = {
        "schema": "hepta.local.p0-p6.source-audit.v1", "time_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "sources": {name: git_snapshot(path) for name, path in roots.items()},
        "production_qualified": False, "stages": {},
        "warning": "Source/test results are NOT signed independent target-host/model acceptance; no deployment rights are conferred.",
    }
    for stage, spec in STAGES.items():
        stage_result: dict[str, Any] = {"status": "BLOCKED", "files": [], "checks": [], "external_evidence_needed": spec["external"]}
        source_names = {name for name, _ in spec["required"]}
        before_checks = {name: git_snapshot(roots[name]) for name in source_names}
        missing = []
        unpinned = []
        for name, rel in spec["required"]:
            pin = required_file_pin(roots[name], rel)
            stage_result["files"].append({"path": f"{name}/{rel}", **pin})
            if not pin["present"]:
                missing.append(f"{name}/{rel}")
            elif not pin["pinned"]:
                unpinned.append(f"{name}/{rel}")
        stage_result["missing_files"] = missing
        stage_result["unpinned_files"] = unpinned
        if missing:
            stage_result["status"] = "BLOCKED_SOURCE_NOT_PRESENT"
        elif unpinned:
            stage_result["status"] = "BLOCKED_SOURCE_UNPINNED"
        elif not all(report["sources"][name]["usable"] and before_checks[name]["usable"] for name in source_names):
            stage_result["status"] = "BLOCKED_NO_GIT_CHECKOUT"
        elif not all(report["sources"][name]["clean"] and before_checks[name]["clean"] for name in source_names):
            # A dirty checkout cannot prove which source produced a test result.
            stage_result["status"] = "BLOCKED_DIRTY_WORKTREE"
        elif any(
            before_checks[name][field] != report["sources"][name][field]
            for name in source_names for field in ("commit", "tree")
        ):
            stage_result["status"] = "BLOCKED_SOURCE_IDENTITY_CHANGED"
        elif not args.execute_checks:
            stage_result["status"] = "BLOCKED_NOT_RUN"
        else:
            for index, (name, subdir, argv) in enumerate(spec["checks"]):
                folder = roots[name] / subdir
                stage_result["checks"].append(run_check(argv, folder, args.timeout_sec,
                                                          run_dir / f"{stage.lower()}-{index}.log"))
            states = [c["status"] for c in stage_result["checks"]]
            after_checks = {name: git_snapshot(roots[name]) for name in source_names}
            # Tests may create tracked or untracked files, change checked-out
            # branches or rewrite generated source. Never report success for a
            # test that no longer matches the frozen initial Git identity.
            if any(
                not after_checks[name]["usable"]
                or not after_checks[name]["clean"]
                or any(after_checks[name][field] != report["sources"][name][field]
                       for field in ("commit", "tree"))
                for name in source_names
            ):
                stage_result["status"] = "BLOCKED_SOURCE_CHANGED_DURING_CHECKS"
            else:
                stage_result["status"] = ("SOURCE_TESTED_EXTERNAL_EVIDENCE_PENDING" if all(s == "PASS_LOCAL" for s in states)
                                          else "BLOCKED_CHECKS_FAILED_OR_UNAVAILABLE")
        report["stages"][stage] = stage_result
    results_path = run_dir / "acceptance.json"
    fd = os.open(results_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps({"report": str(results_path), "source_shas": {k: v.get("commit") for k, v in report["sources"].items()},
                      "stages": {k: v["status"] for k, v in report["stages"].items()},
                      "production_qualified": False}, ensure_ascii=False, indent=2))
    # Never return success: this runner cannot independently prove production
    # effect/readback provenance or operator admission even if all unit checks pass.
    return 3 if all(v["status"] == "SOURCE_TESTED_EXTERNAL_EVIDENCE_PENDING" for v in report["stages"].values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
