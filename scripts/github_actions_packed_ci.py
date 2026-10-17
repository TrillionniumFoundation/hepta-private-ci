#!/usr/bin/env python3
"""Execute distinct real unittest methods on one SHA-pinned runner, with receipts.

This is an opt-in throughput alternative to 500 short one-test-per-runner jobs.
One checkout executes a bounded, deterministic subset. Every case runs in a
fresh Python subprocess; no failed, timed-out or missing case becomes PASS.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

from scripts.github_actions_fleet_500 import collect_tests, plan

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
ALLOWED_WORKERS = frozenset({8, 16, 32})


def select_cases(root: Path, cohort: str, worker_count: int, worker_index: int) -> dict:
    """Partition canonical A, B, or the ALL union without duplicate methods."""
    if cohort not in {"A", "B", "ALL"}:
        raise ValueError("cohort must be A, B or ALL")
    if type(worker_count) is not int or worker_count not in ALLOWED_WORKERS:
        raise ValueError("worker count must be 8, 16 or 32")
    if type(worker_index) is not int or not 0 <= worker_index < worker_count:
        raise ValueError("worker index out of range")
    tests = collect_tests(root)
    selected_a = plan(tests, "A", 250)
    selected_b = plan(tests, "B", 250)
    if not selected_a["slice_ready"] or not selected_b["slice_ready"]:
        raise ValueError("source tree must have >=500 distinct static unittest cases")
    if selected_a["manifest_sha256"] != selected_b["manifest_sha256"]:
        raise ValueError("A/B source manifest mismatch")
    a = [x["case"] for x in selected_a["matrix"]["include"]]
    b = [x["case"] for x in selected_b["matrix"]["include"]]
    if len(a) != 250 or len(b) != 250 or len(set(a + b)) != 500:
        raise ValueError("A/B inventory is incomplete or overlapping")
    cases = a if cohort == "A" else b if cohort == "B" else a + b
    subset = cases[worker_index::worker_count]
    if not subset:
        raise ValueError("empty real worker shard")
    return {
        "worker_count": worker_count,
        "worker_index": worker_index,
        "cohort": cohort,
        "all_case_count": len(cases),
        "selected_cases": subset,
        "manifest_sha256": selected_a["manifest_sha256"],
        "case_set_sha256": hashlib.sha256("\n".join(subset).encode()).hexdigest(),
    }


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), *args], text=True, stderr=subprocess.PIPE
    ).strip()


def verify_source(root: Path, expected_sha: str) -> None:
    if not SHA_RE.fullmatch(expected_sha):
        raise ValueError("expected_sha must be a complete 40-hex commit")
    actual = git(root, "rev-parse", "HEAD")
    if actual != expected_sha:
        raise ValueError(f"checkout identity mismatch: {actual} != {expected_sha}")
    status = git(root, "status", "--porcelain", "--untracked-files=normal")
    if status:
        raise ValueError(
            "uncommitted or untracked source state: refusing ambiguous test input"
        )


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_receipt(path: Path, receipt: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(receipt, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    ).encode()
    fd, tmp = tempfile.mkstemp(prefix=".packed-", suffix=".json.tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(payload)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def run_cases(
    root: Path,
    expected_sha: str,
    schedule: dict,
    receipt_path: Path,
    *,
    timeout_seconds: int = 120,
    runner=None,
) -> dict:
    """Run all planned cases; write a result after every case and exit nonzero on failure.

    The optional runner is a test-only injection; production uses subprocess.run.
    Unstarted cases stay explicitly unexecuted in a failed/incomplete receipt.
    """
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 600:
        raise ValueError("per-case timeout must be 1..600 seconds")
    verify_source(root, expected_sha)
    expected = schedule["selected_cases"]
    if not expected or len(set(expected)) != len(expected):
        raise ValueError("invalid or duplicate worker test set")
    receipt = {
        "version": 1,
        "source_sha": expected_sha,
        "cohort": schedule["cohort"],
        "worker_count": schedule["worker_count"],
        "worker_index": schedule["worker_index"],
        "manifest_sha256": schedule["manifest_sha256"],
        "case_set_sha256": schedule["case_set_sha256"],
        "expected_cases": len(expected),
        "started_at": utcnow(),
        "completed_at": None,
        "status": "running",
        "cases": [],
    }
    atomic_receipt(receipt_path, receipt)
    runner = runner or subprocess.run
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["CODEX_REPO_ROOT"] = str(root)
    env["PYTHONPATH"] = os.pathsep.join((str(root), str(root / "scripts")))
    any_bad = False
    for index, case in enumerate(expected):
        beginning = time.monotonic()
        print(f"TEST_START {index + 1}/{len(expected)} {case}", flush=True)
        try:
            completed = runner(
                [sys.executable, "-m", "unittest", "-v", case],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
            raw = (completed.stdout or "") + "\n" + (completed.stderr or "")
            result = {
                "case": case,
                "status": "passed" if completed.returncode == 0 else "failed",
                "exit_code": completed.returncode,
                "output_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                "elapsed_ms": round((time.monotonic() - beginning) * 1000),
            }
            if completed.returncode:
                any_bad = True
                print("FAILURE_OUTPUT_TAIL\n" + raw[-3000:], flush=True)
        except subprocess.TimeoutExpired:
            any_bad = True
            result = {
                "case": case,
                "status": "timed_out",
                "exit_code": None,
                "output_sha256": None,
                "elapsed_ms": round((time.monotonic() - beginning) * 1000),
            }
        except OSError as exc:
            any_bad = True
            result = {
                "case": case,
                "status": "execution_error",
                "exit_code": None,
                "error_type": type(exc).__name__,
                "output_sha256": None,
                "elapsed_ms": round((time.monotonic() - beginning) * 1000),
            }
        receipt["cases"].append(result)
        print(f"TEST_DONE {result['status']} {case}", flush=True)
        try:
            verify_source(root, expected_sha)
        except (ValueError, subprocess.CalledProcessError):
            any_bad = True
            receipt["status"] = "source_changed"
            atomic_receipt(receipt_path, receipt)
            return receipt
        atomic_receipt(receipt_path, receipt)
    receipt["completed_at"] = utcnow()
    receipt["status"] = "failed" if any_bad else "passed"
    atomic_receipt(receipt_path, receipt)
    return receipt


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=Path.cwd())
    p.add_argument("--cohort", choices=("A", "B", "ALL"), required=True)
    p.add_argument("--workers", type=int, required=True)
    p.add_argument("--worker-index", type=int, required=True)
    p.add_argument("--expected-sha", required=True)
    p.add_argument("--receipt", type=Path, required=True)
    p.add_argument("--timeout-seconds", type=int, default=120)
    p.add_argument("--execute", action="store_true")
    args = p.parse_args(argv)
    try:
        root = args.root.resolve()
        verify_source(root, args.expected_sha)
        schedule = select_cases(root, args.cohort, args.workers, args.worker_index)
        if not args.execute:
            print(
                json.dumps(
                    {
                        "source_sha": args.expected_sha,
                        "cohort": schedule["cohort"],
                        "worker_index": schedule["worker_index"],
                        "worker_count": schedule["worker_count"],
                        "selected_cases": schedule["selected_cases"],
                        "manifest_sha256": schedule["manifest_sha256"],
                        "executed": False,
                    },
                    sort_keys=True,
                )
            )
            return 0
        receipt = run_cases(
            root,
            args.expected_sha,
            schedule,
            args.receipt,
            timeout_seconds=args.timeout_seconds,
        )
        print(
            json.dumps(
                {
                    "status": receipt["status"],
                    "source_sha": args.expected_sha,
                    "cohort": args.cohort,
                    "worker_index": args.worker_index,
                    "expected_cases": receipt["expected_cases"],
                    "completed_cases": len(receipt["cases"]),
                    "passed": sum(x["status"] == "passed" for x in receipt["cases"]),
                    "receipt": str(args.receipt),
                },
                sort_keys=True,
            )
        )
        return 0 if receipt["status"] == "passed" else 1
    except (ValueError, OSError, subprocess.CalledProcessError, SyntaxError) as exc:
        print(f"packed-ci: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
