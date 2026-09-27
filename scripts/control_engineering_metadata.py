#!/usr/bin/env python3
"""Synchronize control.engineering machine-readable implementation metadata.

This generator updates navigation and status projections only. It never changes
production, activation, acceptance, deployment, merge, or release authority.
Exact candidate commit/tree identity remains a CI execution-receipt fact.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "docs/modules/control.engineering/IMPLEMENTATION_MAP.json"
COMPONENTS_PATH = ROOT / "docs/modules/control.engineering/COMPONENTS.json"
TRACEABILITY_PATH = ROOT / "docs/modules/control.engineering/TRACEABILITY.json"
STATUS_PATH = ROOT / "docs/modules/control.engineering/STATUS.json"

AUTHORITY = {
    "runtimeAuthority": False,
    "mergeAuthority": False,
    "activationAuthority": False,
    "promotionAuthority": False,
    "releaseAuthority": False,
    "externalEffectAuthority": False,
    "independentAcceptance": False,
    "canonicalSelection": False,
}

OPERATIONS = (
    {
        "operation": "renew_worker_registration",
        "designOperation": "worker_registration_renewal_and_key_rotation",
        "nativeSymbol": "renew_worker_registration",
        "sourcePath": "tools/hepta-engineering-control/control_engineering_v2/worker_registration.py",
        "state": "source_implemented",
        "authority": "none",
        "tests": [{"path": "tools/hepta-engineering-control/test_worker_registration_renewal.py"}],
        "sourcePathExists": True,
        "mappingClass": "owner_native",
        "delegatedCallees": [{"path": "tools/hepta-engineering-control/control_engineering_v2/worker_lifecycle.py", "symbol": "register_worker", "role": "predecessor_registration_owner"}],
    },
    {
        "operation": "validate_signed_window",
        "designOperation": "clock_skew_and_replay_window_policy",
        "nativeSymbol": "validate_signed_window",
        "sourcePath": "tools/hepta-engineering-control/control_engineering_v2/clock_policy.py",
        "state": "source_implemented",
        "authority": "none",
        "tests": [{"path": "tools/hepta-engineering-control/test_clock_policy.py"}],
        "sourcePathExists": True,
        "mappingClass": "owner_native",
        "delegatedCallees": [],
    },
    {
        "operation": "verify_audit_suffix",
        "designOperation": "incremental_audit_checkpoint_verification",
        "nativeSymbol": "verify_audit_suffix",
        "sourcePath": "tools/hepta-engineering-control/control_engineering_v2/audit_checkpoint.py",
        "state": "source_implemented",
        "authority": "none",
        "tests": [{"path": "tools/hepta-engineering-control/test_audit_checkpoint.py"}, {"path": "tools/hepta-engineering-control/test_audit_checkpoint_incremental.py"}],
        "sourcePathExists": True,
        "mappingClass": "owner_native",
        "delegatedCallees": [{"path": "tools/hepta-engineering-control/control_engineering_v2/control_plane.py", "symbol": "EngineeringStore.audit_anchor", "role": "audit_owner"}],
    },
    {
        "operation": "verify_owner_state_anchor",
        "designOperation": "incremental_owner_state_anchor",
        "nativeSymbol": "verify_owner_state_anchor",
        "sourcePath": "tools/hepta-engineering-control/control_engineering_v2/audit_checkpoint.py",
        "state": "source_implemented",
        "authority": "none",
        "tests": [{"path": "tools/hepta-engineering-control/test_audit_checkpoint.py"}, {"path": "tools/hepta-engineering-control/test_audit_checkpoint_incremental.py"}],
        "sourcePathExists": True,
        "mappingClass": "owner_native",
        "delegatedCallees": [{"path": "tools/hepta-engineering-control/control_engineering_v2/external_controls.py", "symbol": "store_snapshot_digest", "role": "digest_compatibility_reference"}],
    },
    {
        "operation": "require_new_work_capacity",
        "designOperation": "sqlite_capacity_and_migration_admission",
        "nativeSymbol": "require_new_work_capacity",
        "sourcePath": "tools/hepta-engineering-control/control_engineering_v2/capacity_policy.py",
        "state": "source_implemented",
        "authority": "none",
        "tests": [{"path": "tools/hepta-engineering-control/test_capacity_policy.py"}],
        "sourcePathExists": True,
        "mappingClass": "owner_native",
        "delegatedCallees": [{"path": "tools/hepta-engineering-control/control_engineering_v2/product_runtime.py", "symbol": "EngineeringControlProduct._admit_new_work", "role": "product_admission"}],
    },
    {
        "operation": "verify_production_acceptance_bundle",
        "designOperation": "external_provider_and_operator_evidence_admission",
        "nativeSymbol": "verify_production_acceptance_bundle",
        "sourcePath": "tools/hepta-engineering-control/control_engineering_v2/production_providers.py",
        "state": "source_implemented_external_evidence_required",
        "authority": "none",
        "tests": [{"path": "tools/hepta-engineering-control/test_production_providers.py"}],
        "sourcePathExists": True,
        "mappingClass": "owner_native",
        "delegatedCallees": [{"path": "tools/hepta-engineering-control/control_engineering_v2/external_controls.py", "symbol": "verify_production_controls", "role": "typed_external_control_verifier"}],
    },
    {
        "operation": "run_recovery_rehearsal",
        "designOperation": "backup_restore_and_rollback_rehearsal",
        "nativeSymbol": "run_recovery_rehearsal",
        "sourcePath": "tools/hepta-engineering-control/control_engineering_v2/recovery_rehearsal.py",
        "state": "source_implemented_target_host_execution_required",
        "authority": "none",
        "tests": [{"path": "tools/hepta-engineering-control/test_recovery_rehearsal.py"}],
        "sourcePathExists": True,
        "mappingClass": "owner_native",
        "delegatedCallees": [{"path": "tools/hepta-engineering-control/control_engineering_v2/control_plane.py", "symbol": "EngineeringStore", "role": "restore_validator"}],
    },
    {
        "operation": "run_engineering_stress",
        "designOperation": "bounded_wal_crash_reopen_and_growth_profile",
        "nativeSymbol": "run_engineering_stress",
        "sourcePath": "tools/hepta-engineering-control/control_engineering_v2/stress_profile.py",
        "state": "source_implemented_scheduled_soak_pending",
        "authority": "none",
        "tests": [{"path": "tools/hepta-engineering-control/test_stress_profile.py"}],
        "sourcePathExists": True,
        "mappingClass": "owner_native",
        "delegatedCallees": [{"path": "tools/hepta-engineering-control/control_engineering_v2/control_plane.py", "symbol": "EngineeringStore", "role": "durable_owner"}],
    },
)

COMPONENTS = (
    {"id": "worker-registration-renewal", "source": "tools/hepta-engineering-control/control_engineering_v2/worker_registration.py", "symbols": ["WorkerRegistrationRenewalReceipt", "renew_worker_registration"], "state": "source_implemented", "physicalState": "revisioned SQLite worker_registrations row and hash-linked audit event", "failureModel": ["stale_worker_revision", "worker_registration_predecessor_mismatch", "worker_registration_rotation_active_claims", "worker_registration_capacity_below_reservation"], "resourceBounds": {"maximumSkills": 64, "maximumCapacityUnits": 1000000}, "rollback": "retain the predecessor identity until all active claims drain; never rewrite a committed revision"},
    {"id": "signed-clock-window-policy", "source": "tools/hepta-engineering-control/control_engineering_v2/clock_policy.py", "symbols": ["ClockSkewPolicy", "validate_signed_window"], "state": "source_implemented", "failureModel": ["clock_policy_required", "signed_observation_too_old", "signed_observation_from_future", "signed_validity_window_too_wide"], "resourceBounds": {"maximumNanoseconds": 9223372036854775807}, "rollback": "fall back to the strict zero-future-skew policy"},
    {"id": "incremental-audit-checkpoint", "source": "tools/hepta-engineering-control/control_engineering_v2/audit_checkpoint.py", "symbols": ["AuditCheckpointReceipt", "OwnerStateAnchorReceipt", "verify_audit_suffix", "verify_owner_state_anchor"], "state": "source_implemented_external_checkpoint_required", "failureModel": ["audit_checkpoint_signature", "audit_checkpoint_sequence_gap", "audit_chain_broken", "owner_state_anchor_snapshot_mismatch"], "resourceBounds": {"maximumSuffixRows": 1000000}, "rollback": "discard the checkpoint and execute the existing full-chain verifier"},
    {"id": "sqlite-capacity-policy", "source": "tools/hepta-engineering-control/control_engineering_v2/capacity_policy.py", "symbols": ["ControlCapacityPolicy", "evaluate_control_capacity", "require_new_work_capacity"], "state": "source_implemented_target_profile_required", "failureModel": ["control_capacity_hard_limit"], "resourceBounds": {"referenceDatabaseBytes": 8589934592, "referenceWalBytes": 2147483648, "referenceAuditEvents": 10000000}, "rollback": "stop only new-work admission while completion, recovery and terminal reconciliation remain available"},
    {"id": "external-production-provider-boundary", "source": "tools/hepta-engineering-control/control_engineering_v2/production_providers.py", "symbols": ["ProductionProviderSet", "ProductionEvidenceBundle", "verify_production_acceptance_bundle"], "state": "source_implemented_real_providers_pending", "failureModel": ["external_provider_not_independent", "production_provider_role_collision", "production_provider_signing_identity_collision", "operator_acceptance_binding"], "resourceBounds": {"requiredIndependentRoles": 8}, "rollback": "keep production_implementation false and reject the evidence bundle"},
    {"id": "recovery-rehearsal", "source": "tools/hepta-engineering-control/control_engineering_v2/recovery_rehearsal.py", "symbols": ["RecoveryRehearsalReport", "run_recovery_rehearsal"], "state": "source_implemented_target_host_execution_pending", "failureModel": ["recovery_rehearsal_backup_exists", "recovery_rehearsal_backup_integrity", "recovery_rehearsal_mismatch"], "resourceBounds": {"copyMethod": "sqlite_online_backup"}, "rollback": "never overwrite the only surviving database; restore to a new path"},
    {"id": "bounded-stress-profile", "source": "tools/hepta-engineering-control/control_engineering_v2/stress_profile.py", "symbols": ["EngineeringStressReport", "run_engineering_stress"], "state": "source_implemented_scheduled_soak_pending", "failureModel": ["stress_crash_probe_failed", "stress_crash_transaction_visible", "stress_record_count_mismatch"], "resourceBounds": {"maximumWorkers": 32, "maximumRecords": 100000, "maximumReopenCycles": 10000}, "rollback": "qualification evidence only; never promote from a stress result"},
)

TRACE_OPERATIONS = (
    {"designOperation": "worker_registration_renewal_and_key_rotation", "nativeModule": "control_engineering_v2.worker_registration", "nativeSymbol": "renew_worker_registration", "ownerSymbol": "EngineeringControlProduct.renew_worker", "tests": ["WorkerRegistrationRenewalTests.test_rotation_is_revision_bound_and_replay_stable", "WorkerRegistrationRenewalTests.test_profile_or_key_rotation_is_rejected_while_claim_is_active", "WorkerRegistrationRenewalTests.test_stale_predecessor_fails_closed"], "state": "source_implemented", "capabilityCeiling": "authority-signed revision-bound renewal or key/profile rotation; no execution, merge, deployment or release authority"},
    {"designOperation": "clock_skew_and_replay_window_policy", "nativeModule": "control_engineering_v2.clock_policy", "nativeSymbol": "validate_signed_window", "ownerSymbol": "EngineeringControlProduct._validate_receipt_window", "tests": ["ClockPolicyTests.test_strict_policy_preserves_no_future_observation_rule", "ClockPolicyTests.test_measured_skew_age_and_validity_are_all_enforced"], "state": "source_implemented", "capabilityCeiling": "additional fail-closed product admission and measured external receipt validation only"},
    {"designOperation": "incremental_audit_checkpoint_verification", "nativeModule": "control_engineering_v2.audit_checkpoint", "nativeSymbol": "verify_audit_suffix", "ownerSymbol": "verify_audit_suffix", "tests": ["AuditCheckpointTests.test_signed_checkpoint_verifies_suffix_and_owner_anchor", "IncrementalOwnerAnchorTests.test_owner_anchor_does_not_rescan_verified_audit_prefix"], "state": "source_implemented", "capabilityCeiling": "externally signed prefix checkpoint plus locally verified suffix; no authority granted"},
    {"designOperation": "sqlite_capacity_and_migration_admission", "nativeModule": "control_engineering_v2.capacity_policy", "nativeSymbol": "require_new_work_capacity", "ownerSymbol": "EngineeringControlProduct._admit_new_work", "tests": ["CapacityPolicyTests.test_migration_signal_and_hard_new_work_gate_are_distinct"], "state": "source_implemented", "capabilityCeiling": "new-work admission only; completion, recovery and reconciliation remain available"},
    {"designOperation": "external_provider_and_operator_evidence_admission", "nativeModule": "control_engineering_v2.production_providers", "nativeSymbol": "verify_production_acceptance_bundle", "ownerSymbol": "verify_production_acceptance_bundle", "tests": ["ProductionProviderTests.test_non_fixture_bundle_requires_all_evidence_and_operator", "ProductionProviderTests.test_fixture_role_or_key_custody_collision_is_never_eligible"], "state": "source_implemented_external_evidence_required", "capabilityCeiling": "verifies non-fixture external evidence but deliberately leaves production_implementation and release authority false"},
    {"designOperation": "backup_restore_and_rollback_rehearsal", "nativeModule": "control_engineering_v2.recovery_rehearsal", "nativeSymbol": "run_recovery_rehearsal", "ownerSymbol": "run_recovery_rehearsal", "tests": ["RecoveryRehearsalTests.test_backup_restore_rehearsal_binds_snapshot_and_refuses_overwrite"], "state": "source_implemented_target_host_execution_required", "capabilityCeiling": "local verified backup/restore report only; no target switch or operator acceptance"},
    {"designOperation": "bounded_wal_crash_reopen_and_growth_profile", "nativeModule": "control_engineering_v2.stress_profile", "nativeSymbol": "run_engineering_stress", "ownerSymbol": "run_engineering_stress", "tests": ["StressProfileTests.test_concurrent_growth_crash_and_reopen_profile_is_bounded"], "state": "source_implemented_scheduled_soak_pending", "capabilityCeiling": "bounded qualification measurement only"},
)

GAPS = (
    "Retain an exact post-merge main product receipt in addition to the pull-request source-head/base-merge pair.",
    "Require an actual non-author review bound to the exact pull-request head; a requested reviewer is not acceptance.",
    "Run the scheduled long-duration contention, WAL, crash/reopen, disk-full and database-growth profile on the selected target host.",
    "Bind real distributed fencing, immutable audit log, HSM/KMS custody, completion/terminal observers, deployment and operator providers.",
)

EXTERNAL_GATES = (
    "independent semantic review bound to the exact source head",
    "real distributed lease/fence service and immutable external audit log",
    "separated HSM/KMS custody for source, CI, review and integration identities",
    "non-fixture completion and terminal integration observers",
    "authorized target-host deployment, backup/restore rollback rehearsal and operator acceptance",
)


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def render(value: object) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def write(path: Path, value: object, *, check: bool) -> bool:
    expected = render(value)
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    changed = current != expected
    if changed and not check:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(expected, encoding="utf-8")
    return changed


def replace_by_key(rows: list[dict[str, Any]], additions: tuple[dict[str, Any], ...], key: str) -> None:
    positions = {row.get(key): index for index, row in enumerate(rows) if isinstance(row, dict) and isinstance(row.get(key), str)}
    for addition in additions:
        value = json.loads(json.dumps(addition))
        identity = value[key]
        if identity in positions:
            rows[positions[identity]] = value
        else:
            positions[identity] = len(rows)
            rows.append(value)


def sync_structure(*, check: bool) -> list[str]:
    changed: list[str] = []
    implementation = load(MAP_PATH)
    replace_by_key(implementation["operations"], OPERATIONS, "operation")
    implementation["productionImplementation"] = False
    implementation["productCallerState"] = "repository_product_caller_dual_lane_and_post_merge_gate_defined"
    implementation["productionWriterState"] = "named_product_owner_composed_external_acceptance_pending"
    boundary = implementation.setdefault("claimBoundary", {})
    boundary["productionImplementation"] = False
    boundary["independentAcceptance"] = False
    boundary["activation"] = False
    boundary["release"] = False
    for gap in GAPS:
        if gap not in implementation.setdefault("repositoryControlledGaps", []):
            implementation["repositoryControlledGaps"].append(gap)
    for gate in EXTERNAL_GATES:
        if gate not in implementation.setdefault("externalEvidenceGates", []):
            implementation["externalEvidenceGates"].append(gate)
    if write(MAP_PATH, implementation, check=check):
        changed.append(str(MAP_PATH.relative_to(ROOT)))
    components = load(COMPONENTS_PATH)
    replace_by_key(components["components"], COMPONENTS, "id")
    components["authorityFlags"] = dict(AUTHORITY)
    if write(COMPONENTS_PATH, components, check=check):
        changed.append(str(COMPONENTS_PATH.relative_to(ROOT)))
    traceability = load(TRACEABILITY_PATH)
    replace_by_key(traceability["operations"], TRACE_OPERATIONS, "designOperation")
    if write(TRACEABILITY_PATH, traceability, check=check):
        changed.append(str(TRACEABILITY_PATH.relative_to(ROOT)))
    return changed


def status_projection() -> dict[str, Any]:
    implementation = load(MAP_PATH)
    components = load(COMPONENTS_PATH)
    traceability = load(TRACEABILITY_PATH)
    operations = [{"operation": row["operation"], "state": row["state"], "sourcePath": row.get("sourcePath"), "tests": row.get("tests", [])} for row in implementation["operations"]]
    return {
        "schema": "hepta.control-engineering-status.v1",
        "schemaVersion": 1,
        "module": "control.engineering",
        "generatedFrom": {"implementationMap": str(MAP_PATH.relative_to(ROOT)), "components": str(COMPONENTS_PATH.relative_to(ROOT)), "traceability": str(TRACEABILITY_PATH.relative_to(ROOT))},
        "sourceIdentity": {"mode": "exact_ci_execution_receipt", "embeddedCommit": False, "reason": "a committed status blob cannot self-embed its own commit/tree; PR dual-lane and post-merge workflows bind the exact candidate"},
        "current": {"sourceRootPresent": bool(implementation["sourceRootPresent"]), "productionImplementation": False, "productCallerState": implementation["productCallerState"], "productionWriterState": implementation["productionWriterState"], "claimBoundary": implementation["claimBoundary"]},
        "inventory": {"operationCount": len(operations), "componentCount": len(components["components"]), "traceabilityOperationCount": len(traceability["operations"])},
        "operations": operations,
        "qualification": {"pullRequestSourceHeadRequired": True, "pullRequestSyntheticMergeRequired": True, "postMergeMainReceiptRequired": True, "strongSandboxRequired": True, "productCallerFailureBlocksRelease": True, "statusArtifactBindsExactShaAtRuntime": True},
        "remainingToTarget": {"repositoryControlledGaps": implementation.get("repositoryControlledGaps", []), "externalEvidenceGates": implementation.get("externalEvidenceGates", [])},
        "authority": dict(AUTHORITY),
    }


def sync_status(*, check: bool) -> list[str]:
    changed = write(STATUS_PATH, status_projection(), check=check)
    return [str(STATUS_PATH.relative_to(ROOT))] if changed else []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["sync-structure", "sync-status", "sync", "check"])
    args = parser.parse_args()
    check = args.command == "check"
    changed: list[str] = []
    if args.command in {"sync-structure", "sync", "check"}:
        changed.extend(sync_structure(check=check))
    if args.command in {"sync-status", "sync", "check"}:
        changed.extend(sync_status(check=check))
    print(json.dumps({"module": "control.engineering", "command": args.command, "changed": sorted(set(changed)), "checkOnly": check, "authorityGranted": False}, sort_keys=True))
    if check and changed:
        raise SystemExit("FAIL_CONTROL_ENGINEERING_METADATA: drift: " + ", ".join(sorted(set(changed))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
