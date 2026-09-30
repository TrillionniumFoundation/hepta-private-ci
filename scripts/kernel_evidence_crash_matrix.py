#!/usr/bin/env python3
"""Project retained Rust test logs into closed-world crash scenario receipts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time

OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")

SCENARIO_TESTS: dict[str, tuple[str, ...]] = {
    "sqlite_process_kill": (
        "authbus_outbox_tests::actual_process_crash_after_send_before_ack_redelivers_same_id",
        "provider_effect_tests::qualification_crash_after_send_reopen_reconciles_without_redispatch",
    ),
    "wal_rollback_journal": (
        "recovery_frontier::tests::recovery_snapshot_retains_one_wal_read_epoch",
        "qualification_tests::failed_evidence_insert_rolls_back_authbus_replay_advance",
    ),
    "fsync_rename_directory_fsync": (
        "frontier_backend_file::tests::locked_backend_linearizes_cas_and_returns_durable_acknowledgements",
        "frontier_backend_file::tests::locked_backend_rejects_replaced_journal_directory",
        "frontier_backend_file::tests::locked_backend_rejects_torn_audit_tails",
    ),
    "disk_full": (
        "store::runtime::tests::disk_full_fault_is_atomic_and_database_remains_integrity_checkable",
        "frontier_backend_file::tests::append_capacity_is_rejected_before_a_write_starts",
    ),
    "damaged_frontier": (
        "frontier_backend_file::recovery::tests::recovery_rejects_a_substituted_digest",
        "frontier_backend_file::recovery::tests::torn_tail_prevents_recovery_even_of_an_earlier_record",
    ),
    "damaged_database": (
        "qualification_tests::evid_03_corrupted_canonical_payload_fails_reopen",
        "tests::corrupted_stored_digest_fails_closed",
    ),
    "stale_valid_frontier": (
        "frontier_backend_file::tests::locked_backend_rejects_stale_or_skipped_generations",
        "frontier_acceptance::tests::rollback_and_same_generation_identity_changes_fail_closed",
    ),
    "legacy_import": (
        "provider_effect_tests::imported_pending_is_quarantined_before_dispatch_and_reconcile_only",
        "provider_tests::migration_0006_backfills_ephemeral_projection_without_rewriting_evidence",
    ),
    "simultaneous_database_frontier_rollback": (
        "authbus_recovery::tests::external_checkpoint_detects_real_old_database_restore",
        "frontier_backend_file::tests::production_open_rejects_a_backend_in_the_local_rollback_device",
    ),
    "backup_restore": (
        "evidence_production::tests::backup_publication_binds_real_object_build_and_restore_witness",
        "frontier_backend_file::segmented::tests::archived_acknowledgement_is_recoverable_after_reopen",
    ),
    "multi_process_contention": (
        "frontier_backend_file::tests::concurrent_first_generation_publish_has_exactly_one_winner",
        "authbus_store::tests::independent_database_handles_cannot_both_admit_one_sequence",
    ),
    "repair_append_concurrency": (
        "frontier_backend_file::recovery::tests::recovery_lock_contention_is_bounded_and_does_not_append",
        "provider_effect_tests::qualification_boundary_lock_serializes_lookup_against_dispatch",
    ),
}


def atomic_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=".crash-matrix-")
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--tested-sha", required=True)
    parser.add_argument("--target-triple", required=True)
    parser.add_argument("--workflow-run-id", required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--command", required=True)
    args = parser.parse_args()
    if OID.fullmatch(args.tested_sha) is None:
        parser.error("tested SHA must be a full lowercase Git object id")
    payload = args.log.read_bytes()
    text = payload.decode("utf-8", errors="replace")
    log_sha256 = hashlib.sha256(payload).hexdigest()
    now = int(time.time() * 1000)
    passed_all = True
    for scenario, tests in SCENARIO_TESTS.items():
        missing = [name for name in tests if f"test {name} ... ok" not in text]
        passed = not missing
        passed_all = passed_all and passed
        receipt: dict[str, object] = {
            "schemaVersion": 1,
            "module": "kernel.evidence",
            "scenario": scenario,
            "testedSha": args.tested_sha,
            "targetTriple": args.target_triple,
            "qualificationClass": "hosted_runner",
            "status": "passed" if passed else "failed",
            "command": args.command,
            "exitCode": 0 if passed else 1,
            "startedAtUnixMs": now,
            "finishedAtUnixMs": now,
            "workflowRunId": args.workflow_run_id,
            "logSha256": log_sha256,
            "requiredTests": list(tests),
            "missingTests": missing,
            "qualificationGranted": False,
            "targetHostAcceptanceGranted": False,
        }
        atomic_json(args.output_directory / f"{scenario}.json", receipt)
    summary = {
        "schemaVersion": 1,
        "module": "kernel.evidence",
        "testedSha": args.tested_sha,
        "targetTriple": args.target_triple,
        "passed": passed_all,
        "scenarioCount": len(SCENARIO_TESTS),
        "targetHostAcceptanceGranted": False,
    }
    atomic_json(args.output_directory / "SUMMARY.json", summary)
    print(json.dumps(summary, sort_keys=True))
    return 0 if passed_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
