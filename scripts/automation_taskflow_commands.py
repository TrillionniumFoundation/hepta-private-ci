"""Read-only TaskFlow qualification using the repository's real command recorder.

The summary describes observed commands, not a pre-written list of successes.
No source is formatted, committed, pushed, promoted or independently accepted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any


# id, working directory, argv, minimum observed tests, compile dependency.
PLAN = (
    ("contract", ".", ["python3", "scripts/automation_taskflow_contract.py", "self-test"], 0, False),
    ("python", ".", ["python3", "-m", "unittest", "-v", "scripts.test_automation_taskflow_contract", "scripts.test_verify_automation_taskflow_acceptance", "scripts.test_automation_recovery_sweeps", "scripts.test_automation_taskflow_commands"], 14, False),
    ("format", "codex-rs", ["cargo", "fmt", "-p", "codex-hepta-operations", "-p", "codex-hepta-automation", "-p", "codex-hepta-agentd", "--", "--check"], 0, False),
    ("compile", "codex-rs", ["cargo", "check", "--locked", "-p", "codex-hepta-operations", "-p", "codex-hepta-automation", "-p", "codex-hepta-agentd", "--all-targets"], 0, False),
    ("clippy", "codex-rs", ["cargo", "clippy", "--locked", "-p", "codex-hepta-automation", "-p", "codex-hepta-agentd", "--all-targets", "--all-features", "--", "-D", "warnings"], 0, True),
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


def validate_record(record: dict[str, Any], argv: list[str], commit: str, directory: Path,
                    minimum_tests: int) -> bool:
    """Bind actual exit, source, command and retained log; reject missing evidence."""
    before = record.get("before")
    if (record.get("status") != "passed" or record.get("exit_code") != 0
            or record.get("command_exit_code") != 0 or record.get("command") != argv
            or record.get("tested_sha") != commit or not isinstance(before, dict)
            or before.get("commit") != commit or before.get("dirty") is not False
            or before != record.get("after")
            or record.get("timed_out") is not False
            or record.get("output_limit_exceeded") is not False
            or record.get("observed_failed_tests") != 0
            or type(record.get("observed_passed_tests")) is not int
            or record["observed_passed_tests"] < minimum_tests):
        return False
    log_name = record.get("log_file")
    if not isinstance(log_name, str) or Path(log_name).name != log_name:
        return False
    path = directory / log_name
    if not path.is_file() or path.is_symlink():
        return False
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest == record.get("log_sha256")


def qualify(output_dir: Path) -> int:
    # Import only during execution: pure receipt validation can be unit tested
    # without pretending a fixture is native execution.
    from hepta_ci_exec import run

    root = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], text=True).strip()
    output_dir = output_dir.resolve()
    if output_dir.is_relative_to(root.resolve()):
        raise ValueError("receipts must be outside the source checkout")
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "automation-taskflow-command-receipt.json"
    summary: dict[str, Any] = {
        "schema": "hepta.automation-taskflow.command-receipt.v1",
        "evidenceFormat": "actual-command-records.v2",
        "commit": commit, "tree": tree,
        "runId": os.environ.get("GITHUB_RUN_ID"),
        "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "runnerOs": os.environ.get("RUNNER_OS"),
        "runnerArch": os.environ.get("RUNNER_ARCH"),
        "lane": os.environ.get("HEPTA_CI_LANE"),
        "status": "running", "commands": [],
        "independentAcceptance": False, "activation": False,
        "promotion": False, "release": False,
    }
    with summary_path.open("x", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
    compile_passed = False
    original_cwd = Path.cwd()
    try:
        for name, cwd, argv, minimum, requires_compile in PLAN:
            item: dict[str, Any] = {"id": name, "command": argv, "status": "not_run"}
            summary["commands"].append(item)
            if requires_compile and not compile_passed:
                item["reason"] = "compile command did not produce a passing receipt"
                continue
            os.chdir(root / cwd)
            record_path = output_dir / f"{name}.json"
            result = run(record_path, argv, minimum_tests=minimum, timeout_seconds=1800)
            record = json.loads(record_path.read_text(encoding="utf-8"))
            valid = result == 0 and validate_record(record, argv, commit, output_dir, minimum)
            item.update({
                "status": "passed" if valid else "failed",
                "record": record_path.name,
                "recordSha256": hashlib.sha256(record_path.read_bytes()).hexdigest(),
                "exitCode": result,
            })
            if name == "compile":
                compile_passed = valid
    finally:
        os.chdir(original_cwd)
        summary["status"] = (
            "passed" if len(summary["commands"]) == len(PLAN)
            and all(item["status"] == "passed" for item in summary["commands"])
            else "failed"
        )
        pending = summary_path.with_suffix(".pending")
        with pending.open("x", encoding="utf-8") as handle:
            json.dump(summary, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        pending.replace(summary_path)
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
