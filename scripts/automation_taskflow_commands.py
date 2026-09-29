"""Read-only TaskFlow qualification using the repository's real command recorder.

The summary describes observed commands, not a pre-written list of successes.
No source is formatted, committed, pushed, promoted or independently accepted.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any


# id, working directory, argv, minimum observed tests, compile dependency.
PLAN = (
    ("contract", ".", ["python3", "scripts/automation_taskflow_contract.py", "self-test"], 0, False),
    ("python", ".", ["python3", "-m", "unittest", "-v", "scripts.test_automation_taskflow_contract", "scripts.test_verify_automation_taskflow_acceptance", "scripts.test_automation_recovery_sweeps", "scripts.test_automation_taskflow_commands", "scripts.test_automation_taskflow_checkpoint"], 76, False),
    ("rust-toolchain", "codex-rs", ["rustc", "--version", "--verbose"], 0, False),
    ("cargo-toolchain", "codex-rs", ["cargo", "--version", "--verbose"], 0, False),
    ("format", "codex-rs", ["cargo", "fmt", "-p", "codex-hepta-operations", "-p", "codex-hepta-automation", "-p", "codex-hepta-agentd", "--", "--check"], 0, False),
    ("compile", "codex-rs", ["cargo", "check", "--locked", "-p", "codex-hepta-operations", "-p", "codex-hepta-automation", "-p", "codex-hepta-agentd", "--all-targets"], 0, False),
    ("clippy", "codex-rs", ["cargo", "clippy", "--locked", "-p", "codex-hepta-automation", "-p", "codex-hepta-agentd", "--all-targets", "--all-features", "--no-deps", "--", "-D", "warnings"], 0, True),
    ("operations", "codex-rs", ["just", "test", "--locked", "-p", "codex-hepta-operations"], 1, True),
    ("automation", "codex-rs", ["just", "test", "--locked", "-p", "codex-hepta-automation"], 1, True),
    ("structural", "codex-rs", ["just", "test", "--locked", "-p", "codex-hepta-automation", "--features", "taskflow-structural-qualification"], 1, True),
    ("scheduler-review", "codex-rs", ["just", "test", "--locked", "-p", "codex-hepta-automation", "--test", "scheduler_review_regressions"], 4, True),
    ("recovery-review", "codex-rs", ["just", "test", "--locked", "-p", "codex-hepta-automation", "--test", "recovery_owner_review"], 3, True),
    ("migration", "codex-rs", ["just", "test", "--locked", "-p", "codex-hepta-automation", "migration_convergence"], 1, True),
    ("agentd", "codex-rs", ["just", "test", "--locked", "-p", "codex-hepta-agentd", "--lib"], 1, True),
    ("product", "codex-rs", ["just", "test", "--locked", "-p", "codex-hepta-agentd", "--test", "five_agent_rolling_upgrade", "five_real_agentd_processes_roll_one_agent_without_stopping_peers"], 1, True),
    ("bazel", ".", ["bazel", "test", "--test_output=errors", "//codex-rs/hepta-automation:hepta-automation-taskflow-kernel-qualification-test", "//codex-rs/hepta-automation:hepta-automation-taskflow-step-qualification-test"], 0, False),
)


def file_digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def validate_record(record: dict[str, Any], argv: list[str], commit: str, directory: Path,
                    minimum_tests: int, *, expected_tree: str, working_directory: str) -> bool:
    """Bind actual exit, tree, cwd, time interval, test count and retained log."""
    before = record.get("before")
    if (record.get("status") != "passed" or type(record.get("exit_code")) is not int
            or record["exit_code"] != 0 or type(record.get("command_exit_code")) is not int
            or record["command_exit_code"] != 0 or record.get("command") != argv
            or record.get("tested_sha") != commit or not isinstance(before, dict)
            or before.get("commit") != commit or before.get("tree") != expected_tree
            or before.get("dirty") is not False or before != record.get("after")
            or record.get("working_directory") != working_directory
            or record.get("timed_out") is not False or record.get("output_limit_exceeded") is not False
            or type(record.get("observed_failed_tests")) is not int or record["observed_failed_tests"] != 0
            or type(record.get("observed_passed_tests")) is not int or record["observed_passed_tests"] < minimum_tests
            or type(record.get("minimum_tests")) is not int or record["minimum_tests"] != minimum_tests):
        return False
    try:
        started = datetime.fromisoformat(record["started_at"])
        finished = datetime.fromisoformat(record["finished_at"])
        elapsed = record["elapsed_seconds"]
        if (started.utcoffset() is None or finished.utcoffset() is None or finished < started
                or type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0):
            return False
    except (KeyError, TypeError, ValueError):
        return False
    log_name = record.get("log_file")
    if not isinstance(log_name, str) or not log_name or Path(log_name).name != log_name:
        return False
    path = directory / log_name
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 64 * 1024 * 1024:
        return False
    return file_digest(path) == record.get("log_sha256")


def persist_summary(path: Path, summary: dict[str, Any]) -> None:
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as handle:
        pending = Path(handle.name)
        json.dump(summary, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    try:
        pending.replace(path)
        if os.name == "posix":
            fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    finally:
        pending.unlink(missing_ok=True)


def qualify(output_dir: Path) -> int:
    # This is the actual recorder, not a command double or source-writing helper.
    from hepta_ci_exec import run

    root = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip()).resolve()
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], text=True).strip()
    output_dir = output_dir.resolve()
    if output_dir.is_relative_to(root):
        raise ValueError("receipts must be outside the source checkout")
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "automation-taskflow-command-receipt.json"
    summary: dict[str, Any] = {
        "schema": "hepta.automation-taskflow.command-receipt.v1",
        "evidenceFormat": "actual-command-records.v2",
        "commit": commit, "tree": tree, "checkoutDirectory": str(root),
        "runId": os.environ.get("GITHUB_RUN_ID"), "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "runnerOs": os.environ.get("RUNNER_OS"), "runnerArch": os.environ.get("RUNNER_ARCH"),
        "lane": os.environ.get("HEPTA_CI_LANE"), "status": "running",
        "commands": [{"id": name, "command": argv, "workingDirectory": str((root / cwd).resolve()),
                      "minimumObservedTests": minimum, "status": "not_run", "reason": "not reached"}
                     for name, cwd, argv, minimum, _ in PLAN],
        "independentAcceptance": False, "activation": False, "promotion": False, "release": False,
    }
    with summary_path.open("x", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    compile_passed = False
    original_cwd = Path.cwd()
    try:
        for item, (name, cwd, argv, minimum, requires_compile) in zip(summary["commands"], PLAN, strict=True):
            if requires_compile and not compile_passed:
                item["reason"] = "compile command did not produce a passing receipt"
                persist_summary(summary_path, summary)
                continue
            os.chdir(root / cwd)
            record_path = output_dir / f"{name}.json"
            item.update({"status": "running", "expectedRecord": record_path.name})
            item.pop("reason", None)
            persist_summary(summary_path, summary)
            result = run(record_path, argv, minimum_tests=minimum, timeout_seconds=1800)
            record = json.loads(record_path.read_text(encoding="utf-8"))
            valid = result == 0 and validate_record(record, argv, commit, output_dir, minimum,
                                                    expected_tree=tree, working_directory=item["workingDirectory"])
            item.update({"status": "passed" if valid else "failed", "record": record_path.name,
                         "recordSha256": file_digest(record_path), "exitCode": result})
            if name == "compile":
                compile_passed = valid
            persist_summary(summary_path, summary)
    finally:
        os.chdir(original_cwd)
        summary["status"] = "passed" if all(item["status"] == "passed" for item in summary["commands"]) else "failed"
        persist_summary(summary_path, summary)
    return 0 if summary["status"] == "passed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        return qualify(args.output_dir)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(2, f"TaskFlow qualification failed: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
