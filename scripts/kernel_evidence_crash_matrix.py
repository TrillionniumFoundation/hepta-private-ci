#!/usr/bin/env python3
"""Execute the closed-world kernel.evidence crash matrix and retain exact receipts."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import time
from typing import Sequence

OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


@dataclass(frozen=True)
class TestCommand:
    package: str
    target_args: tuple[str, ...]
    test_name: str
    required_markers: tuple[str, ...] = ()

    def argv(self) -> list[str]:
        return [
            "cargo",
            "test",
            "--locked",
            "-p",
            self.package,
            *self.target_args,
            self.test_name,
            "--",
            "--exact",
            "--nocapture",
            "--test-threads=1",
        ]

    @property
    def success_marker(self) -> str:
        return f"test {self.test_name} ... ok"


def evidence_lib(test_name: str, *markers: str) -> TestCommand:
    return TestCommand("codex-hepta-evidence", ("--lib",), test_name, tuple(markers))


def agentd_lib(test_name: str, *markers: str) -> TestCommand:
    return TestCommand("codex-hepta-agentd", ("--lib",), test_name, tuple(markers))


def evidence_integration(target: str, test_name: str, *markers: str) -> TestCommand:
    return TestCommand(
        "codex-hepta-evidence",
        ("--test", target),
        test_name,
        tuple(markers),
    )


SCENARIOS: dict[str, tuple[TestCommand, ...]] = {
    "sqlite_process_kill": (
        evidence_lib(
            "authbus_outbox_tests::actual_process_crash_after_send_before_ack_redelivers_same_id"
        ),
        evidence_lib(
            (
                "provider_effect_tests::qualification_crash_after_send_"
                "reopen_reconciles_without_redispatch"
            )
        ),
    ),
    "wal_rollback_journal": (
        evidence_lib(
            "recovery_frontier::tests::recovery_snapshot_retains_one_wal_read_epoch"
        ),
        evidence_lib(
            "qualification_tests::failed_evidence_insert_rolls_back_authbus_replay_advance"
        ),
        evidence_lib(
            "frontier_repair::rollback_tests::failed_event_insert_rolls_back_repair_row_and_nonce"
        ),
    ),
    "fsync_rename_directory_fsync": (
        evidence_lib(
            (
                "frontier_backend_file::tests::locked_backend_linearizes_cas_"
                "and_returns_durable_acknowledgements"
            )
        ),
        evidence_lib(
            "frontier_backend_file::tests::locked_backend_rejects_replaced_journal_directory"
        ),
        evidence_lib(
            "frontier_backend_file::tests::locked_backend_rejects_torn_audit_tails"
        ),
    ),
    "disk_full": (
        evidence_lib(
            (
                "store::runtime::tests::disk_full_fault_is_atomic_and_"
                "database_remains_integrity_checkable"
            )
        ),
        evidence_lib(
            "frontier_backend_file::tests::append_capacity_is_rejected_before_a_write_starts"
        ),
    ),
    "damaged_frontier": (
        evidence_lib(
            "frontier_backend_file::recovery::tests::recovery_rejects_a_substituted_digest"
        ),
        evidence_lib(
            (
                "frontier_backend_file::recovery::tests::torn_tail_prevents_"
                "recovery_even_of_an_earlier_record"
            )
        ),
        evidence_lib(
            (
                "frontier_backend_file::tests::locked_backend_rejects_"
                "rehashed_non_automatic_history_on_reopen"
            )
        ),
        evidence_lib(
            (
                "frontier_backend_file::segmented::tests::"
                "rehashed_archive_to_active_repair_transition_fails_reopen"
            )
        ),
    ),
    "damaged_database": (
        evidence_lib(
            "qualification_tests::evid_03_corrupted_canonical_payload_fails_reopen"
        ),
        evidence_lib("tests::corrupted_stored_digest_fails_closed"),
    ),
    "stale_valid_frontier": (
        evidence_lib(
            "frontier_backend_file::tests::locked_backend_rejects_stale_or_skipped_generations"
        ),
        evidence_lib(
            (
                "frontier_backend_file::tests::locked_backend_reclassifies_"
                "repair_required_successors_under_the_lock"
            )
        ),
        evidence_lib(
            "frontier_acceptance::tests::rollback_and_same_generation_identity_changes_fail_closed"
        ),
    ),
    "legacy_import": (
        evidence_lib(
            (
                "provider_effect_tests::imported_pending_is_quarantined_"
                "before_dispatch_and_reconcile_only"
            )
        ),
        evidence_lib(
            (
                "provider_tests::migration_0006_backfills_ephemeral_projection_"
                "without_rewriting_evidence"
            )
        ),
    ),
    "simultaneous_database_frontier_rollback": (
        evidence_lib(
            "authbus_recovery::tests::external_checkpoint_detects_real_old_database_restore"
        ),
        evidence_lib(
            (
                "frontier_backend_file::tests::production_open_rejects_a_"
                "backend_in_the_local_rollback_device"
            )
        ),
    ),
    "backup_restore": (
        agentd_lib(
            (
                "evidence_production::tests::backup_publication_binds_real_"
                "object_build_and_restore_witness"
            )
        ),
        evidence_lib(
            (
                "frontier_backend_file::segmented::tests::archived_"
                "acknowledgement_is_recoverable_after_reopen"
            )
        ),
    ),
    "multi_process_contention": (
        evidence_integration(
            "frontier_backend_multiprocess",
            "eight_process_first_generation_contention_has_one_durable_winner",
            "kernel_evidence_multiprocess_contention=",
        ),
        evidence_lib(
            "authbus_store::tests::independent_database_handles_cannot_both_admit_one_sequence"
        ),
    ),
    "repair_append_concurrency": (
        evidence_lib(
            (
                "frontier_backend_file::recovery::tests::recovery_lock_"
                "contention_is_bounded_and_does_not_append"
            )
        ),
        evidence_lib(
            "provider_effect_tests::qualification_boundary_lock_serializes_lookup_against_dispatch"
        ),
    ),
}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=".crash-matrix-"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def validate_oid(value: str, label: str, *, optional: bool = False) -> None:
    if optional and not value:
        return
    if OID.fullmatch(value) is None:
        raise ValueError(f"{label} must be a full lowercase Git object id")


def assess_command(
    spec: TestCommand,
    *,
    exit_code: int,
    output: bytes,
    timed_out: bool,
) -> tuple[bool, list[str], bool]:
    text = output.decode("utf-8", errors="replace")
    markers = (spec.success_marker, *spec.required_markers)
    missing = [marker for marker in markers if marker not in text]
    skipped = "skipping:" in text.lower()
    passed = exit_code == 0 and not timed_out and not missing and not skipped
    return passed, missing, skipped


def run_command(
    spec: TestCommand,
    *,
    workspace: Path,
    log_path: Path,
    timeout_seconds: int,
    environment: dict[str, str] | None = None,
) -> dict[str, object]:
    argv = spec.argv()
    started = int(time.time() * 1000)
    timed_out = False
    try:
        completed = subprocess.run(
            argv,
            cwd=workspace,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=timeout_seconds,
        )
        output = completed.stdout
        exit_code = completed.returncode
    except subprocess.TimeoutExpired as error:
        timed_out = True
        output = (error.stdout or b"") + (error.stderr or b"")
        exit_code = 124
    finished = int(time.time() * 1000)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_bytes(output)
    passed, missing, skipped = assess_command(
        spec,
        exit_code=exit_code,
        output=output,
        timed_out=timed_out,
    )
    return {
        "package": spec.package,
        "targetArgs": list(spec.target_args),
        "testName": spec.test_name,
        "argv": argv,
        "command": shlex.join(argv),
        "startedAtUnixMs": started,
        "finishedAtUnixMs": finished,
        "exitCode": exit_code,
        "timedOut": timed_out,
        "status": "passed" if passed else "failed",
        "logPath": str(log_path),
        "logSha256": sha256_bytes(output),
        "logBytes": len(output),
        "requiredMarkers": [spec.success_marker, *spec.required_markers],
        "missingMarkers": missing,
        "skippedDetected": skipped,
    }


def execute_matrix(
    *,
    workspace: Path,
    output_directory: Path,
    source_head_sha: str,
    source_head_tree: str,
    base_sha: str,
    workflow_sha: str,
    workflow_run_id: str,
    workflow_run_attempt: str,
    runner_image: str,
    target_triple: str,
    timeout_seconds: int,
    scenario_names: Sequence[str] | None = None,
    environment: dict[str, str] | None = None,
) -> dict[str, object]:
    selected = tuple(scenario_names or SCENARIOS.keys())
    unknown = sorted(set(selected) - set(SCENARIOS))
    if unknown:
        raise ValueError(f"unknown crash scenarios: {', '.join(unknown)}")
    output_directory.mkdir(parents=True, exist_ok=True)
    receipts: dict[str, dict[str, object]] = {}
    passed_all = True
    for scenario in selected:
        scenario_started = int(time.time() * 1000)
        command_results: list[dict[str, object]] = []
        for index, spec in enumerate(SCENARIOS[scenario], start=1):
            safe_name = re.sub(r"[^a-zA-Z0-9_.-]+", "_", spec.test_name)
            log_path = output_directory / scenario / f"{index:02d}-{safe_name}.log"
            command_results.append(
                run_command(
                    spec,
                    workspace=workspace,
                    log_path=log_path,
                    timeout_seconds=timeout_seconds,
                    environment=environment,
                )
            )
        scenario_finished = int(time.time() * 1000)
        passed = all(result["status"] == "passed" for result in command_results)
        passed_all = passed_all and passed
        receipt: dict[str, object] = {
            "schemaVersion": 2,
            "module": "kernel.evidence",
            "receiptKind": "crash_consistency_scenario",
            "scenario": scenario,
            "sourceHeadSha": source_head_sha,
            "sourceHeadTree": source_head_tree,
            "baseSha": base_sha,
            "workflowSha": workflow_sha,
            "workflowRunId": workflow_run_id,
            "workflowRunAttempt": workflow_run_attempt,
            "runnerImage": runner_image,
            "targetTriple": target_triple,
            "qualificationClass": "hosted_runner",
            "status": "passed" if passed else "failed",
            "startedAtUnixMs": scenario_started,
            "finishedAtUnixMs": scenario_finished,
            "commands": command_results,
            "qualificationGranted": False,
            "targetHostAcceptanceGranted": False,
            "productionActivationGranted": False,
            "releaseGranted": False,
        }
        receipt_path = output_directory / f"{scenario}.json"
        atomic_json(receipt_path, receipt)
        receipts[scenario] = {
            "path": str(receipt_path),
            "sha256": sha256_file(receipt_path),
            "passed": passed,
        }
    summary: dict[str, object] = {
        "schemaVersion": 2,
        "module": "kernel.evidence",
        "receiptKind": "crash_consistency_matrix",
        "sourceHeadSha": source_head_sha,
        "sourceHeadTree": source_head_tree,
        "baseSha": base_sha,
        "workflowSha": workflow_sha,
        "workflowRunId": workflow_run_id,
        "workflowRunAttempt": workflow_run_attempt,
        "runnerImage": runner_image,
        "targetTriple": target_triple,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "passed": passed_all and len(selected) == len(SCENARIOS),
        "scenarioCount": len(selected),
        "requiredScenarioCount": len(SCENARIOS),
        "scenarios": receipts,
        "targetHostAcceptanceGranted": False,
        "productionActivationGranted": False,
        "releaseGranted": False,
    }
    atomic_json(output_directory / "SUMMARY.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--source-head-sha", required=True)
    parser.add_argument("--source-head-tree", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--workflow-sha", required=True)
    parser.add_argument("--workflow-run-id", required=True)
    parser.add_argument("--workflow-run-attempt", required=True)
    parser.add_argument("--runner-image", required=True)
    parser.add_argument("--target-triple", required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--scenario", action="append", default=[])
    args = parser.parse_args()
    try:
        for label, value in (
            ("source head", args.source_head_sha),
            ("source tree", args.source_head_tree),
            ("base", args.base_sha),
            ("workflow", args.workflow_sha),
        ):
            validate_oid(value, label)
        if args.timeout_seconds <= 0 or args.timeout_seconds > 3600:
            raise ValueError("timeout must be in 1..=3600 seconds")
        if not args.workflow_run_id or not args.workflow_run_attempt:
            raise ValueError("workflow run identity is required")
        environment = os.environ.copy()
        environment.setdefault("CARGO_TERM_COLOR", "never")
        environment.setdefault("RUST_BACKTRACE", "1")
        summary = execute_matrix(
            workspace=args.workspace.resolve(),
            output_directory=args.output_directory.resolve(),
            source_head_sha=args.source_head_sha,
            source_head_tree=args.source_head_tree,
            base_sha=args.base_sha,
            workflow_sha=args.workflow_sha,
            workflow_run_id=args.workflow_run_id,
            workflow_run_attempt=args.workflow_run_attempt,
            runner_image=args.runner_image,
            target_triple=args.target_triple,
            timeout_seconds=args.timeout_seconds,
            scenario_names=args.scenario or None,
            environment=environment,
        )
        print(json.dumps(summary, sort_keys=True))
        return 0 if summary["passed"] is True else 1
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"passed": False, "error": str(error)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
