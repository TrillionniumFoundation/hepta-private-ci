#!/usr/bin/env python3
"""Read-only Hepta owner-gate runner. No model selection, deploy, or merge.

This probe cannot supply original model/data/device/operator evidence. It reports
missing prerequisites as BLOCKED (not PASS) and keeps source-head identity.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile


def run(argv, cwd, log, *, timeout=600):
    with log.open("wb") as fh:
        p = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL,
                             stdout=fh, stderr=subprocess.STDOUT,
                             start_new_session=(os.name == "posix"))
        try:
            code = p.wait(timeout=timeout)
            reason = "completed"
        except subprocess.TimeoutExpired:
            if os.name == "posix":
                os.killpg(p.pid, signal.SIGKILL)
            else:
                p.kill()
            p.wait()
            code, reason = None, "timeout_killed"
    b = log.read_bytes()
    return {"status": "PASS" if code == 0 else "FAIL",
            "exit_code": code, "termination": reason,
            "log_file": str(log), "log_sha256": hashlib.sha256(b).hexdigest(),
            "log_bytes": len(b)}


def git_text(args, cwd):
    p = subprocess.run(["git", *args], cwd=cwd, stdin=subprocess.DEVNULL,
                       capture_output=True, text=True, timeout=15, check=False)
    if p.returncode:
        raise RuntimeError(p.stderr.strip() or f"git {args} returned {p.returncode}")
    return p.stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True,
                        help="Already mounted local project checkout")
    parser.add_argument("--output-dir", type=Path, default=Path("/tmp/hepta-local-gate-probe"))
    parser.add_argument("--execute", action="store_true",
                        help="Execute a bounded, read-only focused gate subset")
    args = parser.parse_args()
    output = args.output_dir.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    repo = args.repo.expanduser().resolve()
    report = {"schema": "hepta.local.readonly-probe.v1",
              "observed_at_utc": datetime.now(timezone.utc).isoformat(),
              "requested_checkout": str(repo), "executed": bool(args.execute),
              "native_local_machine_attested": False, "production_qualified": False,
              "source_head": None, "state": "BLOCKED", "checks": [], "blockers": []}
    try:
        if not (repo / ".git").exists():
            raise RuntimeError("Hepta checkout not mounted: .git missing")
        root = Path(git_text(["rev-parse", "--show-toplevel"], repo)).resolve()
        if root != repo:
            raise RuntimeError(f"Requested path {repo} is not the Git root {root}")
        sha = git_text(["rev-parse", "HEAD"], repo)
        if len(sha) != 40:
            raise RuntimeError("Noncanonical Git source identity")
        report["source_head"] = sha
        original_status = git_text(["status", "--porcelain", "--untracked-files=all"], repo)
        if original_status:
            raise RuntimeError("Checkout has existing tracked/untracked changes; isolated clean worktree required")
        commands = [
            ("v2_cohort_identity", [sys.executable, "-B", "-m", "unittest", "discover", "-s", "qa/ndu-grounded-generation", "-p", "test_cohort_firewall.py", "-v"], 180),
            ("v2_exclusion_registry", [sys.executable, "-B", "-m", "unittest", "discover", "-s", "qa/ndu-grounded-generation", "-p", "test_v2_exclusions.py", "-v"], 180),
            ("v2_capability_audit_contract", [sys.executable, "-B", "-m", "unittest", "discover", "-s", "qa/ndu-grounded-generation", "-p", "test_capability_gate.py", "-v"], 180),
            ("ndu_native", ["cargo", "test", "--locked", "--lib", "-p", "codex-hepta-ndu"], 900),
            ("neuron_native", ["cargo", "test", "--locked", "-p", "codex-hepta-neuron"], 900),
            ("worker_native", ["cargo", "test", "--locked", "-p", "codex-hepta-infer-worker-host"], 900),
            ("ndu_clippy", ["cargo", "clippy", "--locked", "-p", "codex-hepta-ndu", "--all-targets", "--", "-D", "clippy::correctness"], 900),
        ]
        for i, (name, cmd, timeout) in enumerate(commands):
            directory = repo / "codex-rs" if cmd[0] == "cargo" else repo
            if not (directory / "Cargo.toml").exists() and cmd[0] == "cargo":
                report["checks"].append({"name": name, "status": "BLOCKED", "reason": "Cargo.toml absent"})
                continue
            if not shutil.which(cmd[0]):
                report["checks"].append({"name": name, "status": "BLOCKED", "reason": f"{cmd[0]} missing"})
                continue
            if not args.execute:
                report["checks"].append({"name": name, "status": "NOT_RUN", "reason": "use --execute"})
                continue
            log = output / f"{i:02d}-{name}.log"
            try:
                result = run(cmd, directory, log, timeout=timeout)
            except (OSError, ValueError) as exc:
                result = {"status": "BLOCKED", "reason": str(exc)}
            report["checks"].append({"name": name, "command": cmd, **result})
        if git_text(["rev-parse", "HEAD"], repo) != sha:
            report["blockers"].append("Source HEAD changed during qualification")
        if git_text(["status", "--porcelain", "--untracked-files=all"], repo) != original_status:
            report["blockers"].append("Source worktree changed during qualification")
        report["blockers"].extend([
            "Exact-HEAD hosted architecture/blocking-ci/Bazel/V8 require independent terminal receipts",
            "Real pretrained shared-Encoder + multimodal generation + NDU prospective utility unverified",
            "Target-host 64/256/1024/4096-Cell telemetry, signed observer and operator admission unavailable",
        ])
        report["state"] = "FOCUSED_PASS_NOT_PRODUCTION" if (
            args.execute and all(x["status"] == "PASS" for x in report["checks"])
        ) else "BLOCKED"
    except Exception as exc:
        report["blockers"].append(str(exc))
    target = output / "hepta-probe.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"state": report["state"], "source_head": report["source_head"],
                      "report": str(target), "blocker_count": len(report["blockers"])}))
    return 0 if report["state"] == "FOCUSED_PASS_NOT_PRODUCTION" else 2


if __name__ == "__main__":
    raise SystemExit(main())
