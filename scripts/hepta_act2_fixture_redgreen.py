"""Run the existing Circuit fixtures through canonical and symlinked TMPDIRs."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys


BASELINE = "8b1c1789916514471c6cacdf0f6c45467255fef9"
CANDIDATE = "8bebf0a3c207a49bfd0a99367fd6e06f52a6cb98"
TESTS = [
    "circuit_drain::tests::stopped_circuit_blocks_drain_after_reopen_until_original_work_settles",
    "circuit_drain::tests::drain_observation_includes_runs_beyond_the_first_page",
    "circuit_journal::tests::expired::expired_recovery_settles_after_the_lease_allowance_is_exhausted",
    "circuit_journal::tests::expired::expired_recovery_rejects_live_stale_and_changed_original_requests",
    "circuit_journal::tests::expired::recovery_owner_settles_multiple_receipts_without_a_new_lease",
    "circuit_journal::tests::lease_churn_cannot_spend_pending_receipt_slots_across_reopen",
    "circuit_journal::tests::stopped_polling_preserves_original_reconciliation_and_idempotent_retry",
    "circuit_journal::tests::legacy::legacy_stopped_history_reserves_actual_pending_settlement_slots",
    "circuit_learning_outbox::tests::full_queue_preserves_existing_operation_and_corrupt_history_is_rejected",
    "circuit_learning_outbox::tests::completion_claim_and_ack_survive_reopen_without_releasing_delivery",
    "circuit_learning_outbox::tests::unfinished_computation_cannot_enter_learning_queue",
    "circuit_task_readback::tests::task_readback_never_initializes_missing_or_repairs_lost_history",
]
FIXTURE_FILES = {
    "codex-rs/hepta-agentd/src/circuit_credit_signed_tests.rs",
    "codex-rs/hepta-agentd/src/circuit_task_driver_tests.rs",
    "codex-rs/hepta-automation/src/circuit_drain_tests.rs",
    "codex-rs/hepta-automation/src/circuit_expired_recovery_tests.rs",
    "codex-rs/hepta-automation/src/circuit_learning_outbox_tests.rs",
    "codex-rs/hepta-automation/src/circuit_recovery_budget_tests.rs",
    "codex-rs/hepta-automation/src/circuit_task_readback_tests.rs",
}
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def git(repository: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repository), *args], text=True
    ).strip()


def run_stage(
    repository: Path, temporary: Path, records: Path, name: str, sha: str
) -> dict:
    env = os.environ.copy()
    env.update(
        TMPDIR=str(temporary),
        SOURCE_SHA=sha,
        TESTED_SHA=sha,
        HEPTA_CI_LANE="source-head",
    )
    output = records / f"{name}.json"
    command = [
        sys.executable,
        str(repository / "scripts/hepta_ci_exec.py"),
        "--timeout-seconds",
        "2400",
        "--minimum-tests",
        "0" if name == "baseline-alias" else str(len(TESTS)),
        "--output",
        str(output),
        "--",
        "just",
        "test",
        "--locked",
        "-p",
        "codex-hepta-automation",
        "--lib",
        "-E",
        " | ".join(f"test(={test})" for test in TESTS),
        "--status-level",
        "all",
        "--final-status-level",
        "all",
    ]
    with (records / f"{name}.launcher.log").open("wb") as stream:
        completed = subprocess.run(
            command, cwd=repository, env=env, stdout=stream, stderr=subprocess.STDOUT
        )
    record = json.loads(output.read_text())
    log_path = records / record["log_file"]
    log = log_path.read_bytes()
    if hashlib.sha256(log).hexdigest() != record["log_sha256"]:
        raise ValueError(f"{name}: command log digest mismatch")
    if record["source_sha"] != sha or record["tested_sha"] != sha:
        raise ValueError(f"{name}: tested source mismatch")
    if record["before"] != record["after"] or record["before"]["dirty"]:
        raise ValueError(f"{name}: source changed during execution")
    if record["timed_out"] or record["output_limit_exceeded"]:
        raise ValueError(f"{name}: timeout or incomplete log")
    clean = ANSI.sub("", log.decode())
    if name == "baseline-alias":
        failed = {
            line.split()[-1]
            for line in clean.splitlines()
            if re.search(r"\bFAIL\b.*\bcodex-hepta-automation\b", line)
        }
        invalid = {
            test
            for test in TESTS
            if re.search(
                rf"thread '{re.escape(test)}'[^\n]*panicked at[^\n]*\n[^\n]*\bInvalid\b",
                clean,
            )
        }
        if (
            completed.returncode == 0
            or record["observed_passed_tests"] != 0
            or record["observed_failed_tests"] != len(TESTS)
            or failed != set(TESTS)
            or invalid != set(TESTS)
        ):
            raise ValueError(
                "baseline-alias: expected exactly the twelve named Invalid failures"
            )
        interpretation = "EXPECTED_INVALID_FAILURES"
    else:
        if (
            completed.returncode != 0
            or record["observed_passed_tests"] != len(TESTS)
            or record["observed_failed_tests"] != 0
        ):
            raise ValueError(f"{name}: twelve passing tests were not observed")
        interpretation = "PASS"
    return {
        "name": name,
        "interpretation": interpretation,
        "source_sha": sha,
        "source_tree": record["before"]["tree"],
        "cargo_lock_sha256": hashlib.sha256(
            (repository / "codex-rs/Cargo.lock").read_bytes()
        ).hexdigest(),
        "tmpdir": str(temporary),
        "tmpdir_resolved": str(temporary.resolve(strict=True)),
        "tmpdir_is_symlink": temporary.is_symlink(),
        "command_record": output.name,
        "passed": record["observed_passed_tests"],
        "failed": record["observed_failed_tests"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    args = parser.parse_args()
    repository = args.repository.resolve(strict=True)
    work = args.work_root.resolve(strict=True)
    records = work / "records"
    records.mkdir()
    result = {
        "schema_version": 1,
        "status": "INCOMPLETE",
        "scope": "twelve Automation fixtures; no broad CI qualification",
        "driver_sha": git(repository, "rev-parse", "HEAD"),
        "baseline_sha": BASELINE,
        "fixture_candidate_sha": CANDIDATE,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "tests": TESTS,
        "stages": [],
    }
    try:
        if platform.system() != "Darwin":
            raise ValueError("this qualification requires an actual macOS runner")
        changed = set(
            git(repository, "diff", "--name-only", BASELINE, CANDIDATE).splitlines()
        )
        if changed != FIXTURE_FILES:
            raise ValueError("fixture candidate differs from the frozen seven-file repair")
        canonical = work / "canonical-tmp"
        canonical.mkdir()
        alias = work / "alias-tmp"
        alias.symlink_to(canonical, target_is_directory=True)
        if (
            canonical.resolve(strict=True) != canonical
            or alias.resolve(strict=True) == alias
        ):
            raise ValueError("TMPDIR canonical/alias contrast was not established")
        os.environ["CARGO_TARGET_DIR"] = str(work / "target")
        for label, sha, temporary in [
            ("baseline-canonical", BASELINE, canonical),
            ("baseline-alias", BASELINE, alias),
            ("candidate-alias", CANDIDATE, alias),
        ]:
            tree = work / ("baseline" if sha == BASELINE else "candidate")
            if not tree.exists():
                subprocess.run(
                    [
                        "git", "-C", str(repository), "worktree", "add", "--detach",
                        str(tree), sha,
                    ],
                    check=True,
                )
            result["stages"].append(run_stage(tree, temporary, records, label, sha))
        result["status"] = "PASS"
        return 0
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        result["status"] = "FAIL"
        result["error"] = str(error)
        return 1
    finally:
        result["finished_at"] = datetime.now(timezone.utc).isoformat()
        files = sorted(p for p in records.iterdir() if p.is_file())
        result["records"] = [
            {
                "path": p.name,
                "bytes": p.stat().st_size,
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            }
            for p in files
        ]
        (records / "RESULT.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
