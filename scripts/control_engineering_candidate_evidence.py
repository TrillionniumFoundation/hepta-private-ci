#!/usr/bin/env python3
"""Read-only exact-head and fixed-base-merge qualification, with failure evidence.

Run this script from the candidate checkout. Outputs must be outside that tree.
A diagnostic receipt never grants independent acceptance, deployment, or release.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import signal
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE = Path("tools/hepta-engineering-control")
OWNER = MODULE / "control_engineering_v2"


def digest_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def git(root: Path, *arguments: str, env: dict[str, str] | None = None) -> str:
    return subprocess.check_output(
        ["git", *arguments], cwd=root, text=True, env=env, timeout=60,
        stderr=subprocess.PIPE,
    ).strip()


def run_command(
    root: Path, output: Path, label: str, arguments: list[str],
    environment: dict[str, str], *, timeout_seconds: int = 1200,
) -> dict[str, object]:
    if not re.fullmatch(r"[a-z0-9-]+", label):
        raise ValueError("invalid command label")
    output.mkdir(parents=True, exist_ok=True)
    log = output / (label + ".log")
    started = time.monotonic_ns()
    timed_out = False
    error: str | None = None
    with log.open("wb") as stream:
        try:
            process = subprocess.Popen(
                arguments, cwd=root, env=environment, stdout=stream,
                stderr=subprocess.STDOUT, start_new_session=True,
            )
            try:
                code = process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                if os.name == "posix":
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                else:
                    process.kill()
                process.wait()
                code = 124
        except OSError as failure:
            error = type(failure).__name__
            stream.write((error + "\n").encode())
            code = 127
    return {
        "label": label, "argv": arguments, "exitCode": code,
        "status": "passed" if code == 0 else "failed",
        "timedOut": timed_out, "launchError": error,
        "elapsedNs": time.monotonic_ns() - started,
        "logFile": log.name, "logBytes": log.stat().st_size,
        "logSha256": digest_file(log),
    }


def run_unittest_report(root: Path, destination: Path) -> int:
    module = root / MODULE
    sys.path.insert(0, str(module))
    suite = unittest.defaultTestLoader.discover(str(module), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    value = {
        "testsRun": result.testsRun,
        "successful": result.wasSuccessful(),
        "failures": [test.id() for test, _ in result.failures],
        "errors": [test.id() for test, _ in result.errors],
        "skipped": [{"test": test.id(), "reason": reason} for test, reason in result.skipped],
        "expectedFailures": [test.id() for test, _ in result.expectedFailures],
        "unexpectedSuccesses": [test.id() for test in result.unexpectedSuccesses],
    }
    write_json(destination, value)
    return 0 if result.wasSuccessful() and result.testsRun > 0 else 1


def command_plan(root: Path, output: Path) -> list[tuple[str, list[str]]]:
    python = sys.executable
    selected = [str(OWNER / name) for name in (
        "control_plane.py", "path_policy.py", "time_policy.py", "audit_checkpoint.py", "capacity_policy.py",
        "worker_registration.py", "product_runtime.py", "production_adapters.py",
        "deployment_evidence.py", "stress_profile.py", "qualification_mutation.py",
        "product_gate.py", "readiness_manifest.py", "external_controls.py",
    )]
    return [
        ("toolchain", [python, "-m", "pip", "freeze"]),
        ("sqlite-version", [python, "-c", "import sqlite3; print(sqlite3.sqlite_version)"]),
        ("status", [python, "scripts/control_engineering_status.py", "--check"]),
        ("public-api", [python, "scripts/control_engineering_api.py", "--check"]),
        ("runtime-regressions", [python, "-m", "unittest", "-v",
            "test_bounded_owner_regressions", "test_control_engineering_extensions",
            "test_deployment_evidence", "test_owner_snapshot_regressions"]),
        ("collector-regressions", [python, "-m", "unittest", "-v",
            "test_candidate_evidence_collector", "test_candidate_evidence_integrity"]),
        ("all-owner-tests", [python, "-m", "coverage", "run", "--branch",
            "--source=control_engineering_v2", "scripts/control_engineering_candidate_evidence.py",
            "--unittest-report", str(output / "unittest.json")]),
        ("coverage-threshold", [python, "-m", "coverage", "report", "--show-missing", "--fail-under=80"]),
        ("coverage-json", [python, "-m", "coverage", "json", "-o", str(output / "coverage.json")]),
        ("strict-lint", [python, "-m", "ruff", "check", str(OWNER),
            *[str(path.relative_to(root)) for path in sorted((root / MODULE).glob("test_*.py"))],
            "scripts/control_engineering_candidate_evidence.py", "scripts/control_engineering_status.py",
            "scripts/control_engineering_api.py", "scripts/test_hepta_exact_blob_squash.py"]),
        ("typed-boundaries", [python, "-m", "mypy", "--disallow-untyped-defs", "--check-untyped-defs",
            "--ignore-missing-imports", "--follow-imports=skip", *selected]),
        ("exact-blob-regressions", [python, "-m", "unittest", "-v", "scripts/test_hepta_exact_blob_squash.py"]),
        ("development-documents", [python, "scripts/hepta-gap-closure.py", "verify"]),
        ("diff-check", ["git", "diff", "--check"]),
        ("tracked-clean", ["git", "diff", "--exit-code", "HEAD"]),
    ]



def checkout_identity(root: Path) -> dict[str, object]:
    """Observe identity as well as dirtiness; a clean newly committed tree is drift."""
    try:
        return {
            "commit": git(root, "rev-parse", "HEAD"),
            "tree": git(root, "rev-parse", "HEAD^{tree}"),
            "status": git(root, "status", "--porcelain", "--untracked-files=normal"),
            "error": None,
        }
    except (subprocess.SubprocessError, OSError) as error:
        return {"commit": None, "tree": None, "status": None,
                "error": type(error).__name__}


def unittest_report_state(path: Path) -> tuple[bool, bool, str | None]:
    """Fail closed on absent, malformed, oversized or contradictory test evidence."""
    try:
        with path.open("rb") as stream:
            data = stream.read(8 * 1024 * 1024 + 1)
        if len(data) > 8 * 1024 * 1024:
            return False, False, "unittest_report_budget_exceeded"
        result = json.loads(data)
    except (OSError, ValueError, RecursionError) as error:
        return False, False, "unittest_report_" + type(error).__name__
    if (
        not isinstance(result, dict)
        or type(result.get("testsRun")) is not int
        or result["testsRun"] < 1
        or type(result.get("successful")) is not bool
        or any(not isinstance(result.get(key), list) for key in (
            "failures", "errors", "skipped", "expectedFailures", "unexpectedSuccesses"
        ))
    ):
        return False, False, "unittest_report_invalid_shape"
    successful = result["successful"] and not any(result[key] for key in (
        "failures", "errors", "unexpectedSuccesses"
    ))
    no_skips = not result["skipped"] and not result["expectedFailures"]
    return bool(successful), no_skips, None


def command_logs_intact(output: Path, records: list[dict[str, object]]) -> bool:
    """A later command must not silently replace an earlier command's evidence."""
    intact = True
    for record in records:
        try:
            path = output / str(record["logFile"])
            matches = (path.is_file() and not path.is_symlink()
                       and path.stat().st_size == record["logBytes"]
                       and digest_file(path) == record["logSha256"])
        except OSError:
            matches = False
        record["logIntegrityVerified"] = bool(matches)
        intact = intact and bool(matches)
    return intact


def qualify_lane(root: Path, output: Path, source: str, base: str, lane: str) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment.update({
        "PYTHONPATH": str(root / MODULE), "PYTHONDONTWRITEBYTECODE": "1",
        "COVERAGE_FILE": str(output / ".coverage"),
        "MYPY_CACHE_DIR": str(output / "mypy-cache"),
        "RUFF_CACHE_DIR": str(output / "ruff-cache"),
    })
    receipt: dict[str, object] = {
        "schema": "hepta.control-engineering-candidate-evidence.v1",
        "lane": lane, "sourceCommit": source, "sourceTree": git(root, "rev-parse", source + "^{tree}"),
        "baseCommit": base, "baseTree": git(root, "rev-parse", base + "^{tree}"),
        "testedCommit": git(root, "rev-parse", "HEAD"),
        "testedTree": git(root, "rev-parse", "HEAD^{tree}"),
        "testedParents": git(root, "show", "-s", "--format=%P", "HEAD").split(),
        "workflowSha": os.environ.get("GITHUB_WORKFLOW_SHA"),
        "workflowRunId": os.environ.get("GITHUB_RUN_ID"),
        "workflowRunAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "runnerImage": os.environ.get("ImageOS"), "runnerImageVersion": os.environ.get("ImageVersion"),
        "python": platform.python_version(), "platform": platform.platform(),
        "gitVersion": git(root, "--version"),
        "collectorSha256": digest_file(root / "scripts/control_engineering_candidate_evidence.py"),
        "commandRecords": [], "allChecksPassed": False, "noSkippedTests": False,
        "qualificationPassed": False, "independentAcceptance": False,
        "productionAccepted": False, "releaseAuthority": False,
    }
    write_json(output / "receipt.json", receipt)
    records: list[dict[str, object]] = []
    expected = {"commit": receipt["testedCommit"], "tree": receipt["testedTree"],
                "status": "", "error": None}
    identity_preserved = lane != "source-head" or receipt["testedCommit"] == source
    for label, arguments in command_plan(root, output):
        before = checkout_identity(root)
        record = run_command(root, output, label, arguments, environment)
        after = checkout_identity(root)
        record["checkoutBefore"] = before
        record["checkoutAfter"] = after
        identity_preserved = identity_preserved and before == expected and after == expected
        record["sourceIdentityPreserved"] = before == expected and after == expected
        records.append(record)
        receipt["commandRecords"] = records
        write_json(output / "receipt.json", receipt)
        print(lane, label, record["status"], record["exitCode"], flush=True)
    report = output / "unittest.json"
    successful, no_skips, report_error = unittest_report_state(report)
    final_identity = checkout_identity(root)
    receipt["allChecksPassed"] = bool(records) and all(record["exitCode"] == 0 for record in records)
    receipt["testsSuccessful"] = successful
    receipt["noSkippedTests"] = no_skips
    receipt["unittestReportError"] = report_error
    receipt["checkoutIdentityAfter"] = final_identity
    receipt["checkoutStatusAfter"] = final_identity["status"]
    receipt["sourceIdentityPreserved"] = identity_preserved and final_identity == expected
    receipt["commandLogsIntact"] = command_logs_intact(output, records)
    receipt["qualificationPassed"] = bool(
        receipt["allChecksPassed"] and receipt["testsSuccessful"] and receipt["noSkippedTests"]
        and receipt["sourceIdentityPreserved"] and receipt["commandLogsIntact"]
    )
    artifacts = {}
    for path in sorted(output.iterdir()):
        if path.is_file() and path.name != "receipt.json":
            artifacts[path.name] = {"sha256": digest_file(path), "bytes": path.stat().st_size}
    receipt["artifacts"] = artifacts
    write_json(output / "receipt.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-commit")
    parser.add_argument("--base-commit")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--unittest-report", type=Path)
    args = parser.parse_args()
    if args.unittest_report is not None:
        return run_unittest_report(ROOT, args.unittest_report)
    for value in (args.source_commit, args.base_commit):
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
            parser.error("source and base must be full immutable commit IDs")
        if git(ROOT, "cat-file", "-t", value) != "commit":
            parser.error("source and base must identify commits")
    if args.output is None:
        parser.error("an output directory outside the checkout is required")
    output = args.output.resolve()
    if output == ROOT or ROOT in output.parents or output.exists():
        parser.error("output must be a new directory outside the checkout")
    if git(ROOT, "rev-parse", "HEAD") != args.source_commit:
        parser.error("checkout does not match source commit")
    if git(ROOT, "status", "--porcelain", "--untracked-files=normal"):
        parser.error("candidate tracked tree must be clean")
    output.mkdir(parents=True)
    source = qualify_lane(ROOT, output / "source-head", args.source_commit, args.base_commit, "source-head")
    merge = None
    try:
        merged_tree = git(ROOT, "merge-tree", "--write-tree", args.base_commit, args.source_commit)
        if not re.fullmatch(r"[0-9a-f]{40}", merged_tree):
            raise ValueError("merge did not return a unique clean tree")
        environment = dict(os.environ)
        environment.update({
            "GIT_AUTHOR_NAME": "Control Engineering Qualification",
            "GIT_AUTHOR_EMAIL": "qualification@invalid.example",
            "GIT_COMMITTER_NAME": "Control Engineering Qualification",
            "GIT_COMMITTER_EMAIL": "qualification@invalid.example",
            "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+00:00",
            "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+00:00",
        })
        commit = git(ROOT, "commit-tree", merged_tree, "-p", args.base_commit, "-p", args.source_commit,
                     "-m", "Deterministic control.engineering qualification candidate", env=environment)
        with tempfile.TemporaryDirectory(prefix="ce-merge-") as temporary:
            checkout = Path(temporary) / "checkout"
            git(ROOT, "worktree", "add", "--detach", str(checkout), commit)
            try:
                merge = qualify_lane(checkout, output / "synthetic-merge", args.source_commit,
                                     args.base_commit, "synthetic-merge")
            finally:
                git(ROOT, "worktree", "remove", "--force", str(checkout))
    except (subprocess.SubprocessError, OSError, ValueError) as error:
        write_json(output / "merge-setup-failure.json", {
            "sourceCommit": args.source_commit, "baseCommit": args.base_commit,
            "setupSucceeded": False, "errorType": type(error).__name__,
            "diagnostic": str(error),
            "stdout": getattr(error, "output", None),
            "stderr": getattr(error, "stderr", None),
            "qualificationPassed": False,
        })
    passed = bool(source["qualificationPassed"] and merge and merge["qualificationPassed"])
    write_json(output / "summary.json", {
        "sourceCommit": args.source_commit, "baseCommit": args.base_commit,
        "sourceReceiptSha256": digest_file(output / "source-head/receipt.json"),
        "mergeReceiptSha256": digest_file(output / "synthetic-merge/receipt.json") if merge else None,
        "bothLanesQualified": passed, "independentAcceptance": False,
        "productionAccepted": False, "releaseAuthority": False,
    })
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
