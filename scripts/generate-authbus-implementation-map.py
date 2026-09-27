#!/usr/bin/env python3
"""Generate and verify the auth.authbus implementation map.

The map is anchored to the newest commit that touched any declared AuthBus
source root. A later documentation-only map commit therefore does not make the
anchor self-referential, while any source change makes `--check` fail until the
map is regenerated.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "docs/modules/auth.authbus/IMPLEMENTATION_MAP.json"

SOURCE_ROOTS = [
    "codex-rs/hepta-authbus",
    "codex-rs/hepta-authbus-p1-3-qualification",
    "codex-rs/hepta-evidence/src/authbus_outbox.rs",
    "codex-rs/hepta-evidence/src/authbus_store.rs",
    "codex-rs/hepta-evidence/src/authbus_outbox_worker.rs",
    "codex-rs/hepta-agentd/src/authbus_ingress.rs",
    "codex-rs/hepta-agentd/src/authbus_dispatch.rs",
    "codex-rs/hepta-agentd/src/authbus_trust.rs",
    "codex-rs/hepta-agentd/src/evidence_trust.rs",
    "codex-rs/hepta-bao-adapter/src/https_consumer.rs",
]

OPERATIONS: list[dict[str, Any]] = [
    {
        "operation": "authenticate_signed_message",
        "nativeSymbol": "SignedMessage::authenticate",
        "sourcePath": "codex-rs/hepta-authbus/src/signed.rs",
        "state": "source_implemented_sealed_registration",
        "authority": "deny_all",
        "tests": [
            ["codex-rs/hepta-authbus/src/signed_tests.rs", "signed_admission_rejects_payload_and_replay_identity_substitution"],
            ["codex-rs/hepta-authbus-p1-3-qualification/src/lib_tests.rs", "persisted_registration_rejects_forged_revoked_and_epoch_substitution"],
        ],
    },
    {
        "operation": "admit_and_enqueue_signed_message",
        "nativeSymbol": "HeptaEvidenceStore::enqueue_authbus_message",
        "sourcePath": "codex-rs/hepta-evidence/src/authbus_outbox.rs",
        "state": "source_implemented_product_composed_agentd",
        "authority": "none",
        "tests": [
            ["codex-rs/hepta-evidence/src/authbus_outbox_tests.rs", "enqueue_commit_response_loss_is_idempotent_across_reopen"],
            ["codex-rs/hepta-agentd/tests/kernel_evidence_product.rs", "signed evidence product ingress"],
        ],
    },
    {
        "operation": "resolve_message_issuer",
        "nativeSymbol": "AuthBusAuthorityHost::message_issuer",
        "sourcePath": "codex-rs/hepta-authbus/src/host.rs",
        "state": "source_implemented_durable_registry",
        "authority": "none",
        "tests": [["codex-rs/hepta-authbus-p1-3-qualification/src/lib_tests.rs", "authority_host_executes_modern_owner_purpose_sweep_and_settlement_matrix"]],
    },
    {
        "operation": "resolve_settlement_issuer",
        "nativeSymbol": "AuthBusAuthorityHost::settlement_issuer",
        "sourcePath": "codex-rs/hepta-authbus/src/host.rs",
        "state": "source_implemented_durable_purpose_bound_registry",
        "authority": "none",
        "tests": [["codex-rs/hepta-authbus/src/settlement_store_tests.rs", "message_purpose_cannot_be_substituted_for_settlement_purpose"]],
    },
    {
        "operation": "authorize",
        "nativeSymbol": "AuthBusAuthorityHost::authorize",
        "sourcePath": "codex-rs/hepta-authbus/src/host.rs",
        "state": "source_implemented_revision_and_trusted_time_bound",
        "authority": "deny_all",
        "tests": [["codex-rs/hepta-authbus/src/authority_store_tests.rs", "policy authorization tests"]],
    },
    {
        "operation": "reserve_quota",
        "nativeSymbol": "AuthBusAuthorityHost::reserve",
        "sourcePath": "codex-rs/hepta-authbus/src/host.rs",
        "state": "source_implemented_durable_quota_conservation",
        "authority": "none",
        "tests": [["codex-rs/hepta-authbus/src/quota_store_tests.rs", "quota reservation tests"]],
    },
    {
        "operation": "mark_dispatch_attempted",
        "nativeSymbol": "AuthBusAuthorityHost::mark_dispatch_attempted",
        "sourcePath": "codex-rs/hepta-authbus/src/host.rs",
        "state": "source_implemented_external_effect_fence",
        "authority": "none",
        "tests": [["codex-rs/hepta-bao-adapter/src/https_consumer_tests.rs", "real product AuthBus dispatch tests"]],
    },
    {
        "operation": "settle",
        "nativeSymbol": "AuthBusAuthorityHost::settle",
        "sourcePath": "codex-rs/hepta-authbus/src/host.rs",
        "state": "source_implemented_transactional_current_issuer_reload",
        "authority": "none",
        "tests": [
            ["codex-rs/hepta-authbus/src/settlement_store_tests.rs", "settlement_reloads_registry_and_rejects_forged_or_revoked_keys"],
            ["codex-rs/hepta-authbus-p1-3-qualification/src/lib_tests.rs", "authority_host_executes_modern_owner_purpose_sweep_and_settlement_matrix"],
        ],
    },
    {
        "operation": "sweep_expired_reservations",
        "nativeSymbol": "AuthBusAuthorityHost::sweep_expired_reservations",
        "sourcePath": "codex-rs/hepta-authbus/src/host.rs",
        "state": "source_implemented_bounded_maintenance",
        "authority": "none",
        "tests": [["codex-rs/hepta-authbus/src/settlement_store_tests.rs", "bounded_expired_reservation_sweep_refunds_only_undispatched_holds"]],
    },
    {
        "operation": "authority_maintenance_tick",
        "nativeSymbol": "AuthBusAuthorityHost::maintenance_tick",
        "sourcePath": "codex-rs/hepta-authbus/src/operations.rs",
        "state": "source_implemented_bounded_recovery_sweep_checkpoint_alerts",
        "authority": "none",
        "tests": [["codex-rs/hepta-authbus/src/host_tests.rs", "checkpoint_stage_failures_remain_recoverable"]],
    },
    {
        "operation": "hold_single_owner_fence",
        "nativeSymbol": "OwnerFence::acquire",
        "sourcePath": "codex-rs/hepta-authbus/src/owner_fence.rs",
        "state": "source_implemented_process_lifetime_cross_process_fence",
        "authority": "none",
        "tests": [
            ["codex-rs/hepta-authbus/src/host_tests.rs", "second_owner_is_rejected_and_release_allows_reopen"],
            ["codex-rs/hepta-authbus/src/host_tests.rs", "kill_nine_releases_the_process_owner_fence"],
        ],
    },
    {
        "operation": "consume_bao_kv_v2_with_authbus",
        "nativeSymbol": "BaoClient::consume_kv_v2_with_authbus",
        "sourcePath": "codex-rs/hepta-bao-adapter/src/https_consumer.rs",
        "state": "source_composed_product_path_not_activated",
        "authority": "final_use_required",
        "tests": [["codex-rs/hepta-bao-adapter/src/https_consumer_tests.rs", "real TLS product execution tests"]],
    },
]


def run(*args: str) -> str:
    return subprocess.check_output(args, cwd=ROOT, text=True).strip()


def latest_source_commit() -> str:
    return run("git", "log", "-1", "--format=%H", "--", *SOURCE_ROOTS)


def source_blob(commit: str, path: str) -> str:
    return run("git", "rev-parse", f"{commit}:{path}")


def validate_sources() -> None:
    errors: list[str] = []
    for root in SOURCE_ROOTS:
        if not (ROOT / root).exists():
            errors.append(f"missing declared source root: {root}")
    for operation in OPERATIONS:
        path = ROOT / operation["sourcePath"]
        if not path.is_file():
            errors.append(f"missing operation source: {operation['sourcePath']}")
        for test_path, _ in operation["tests"]:
            if not (ROOT / test_path).is_file():
                errors.append(f"missing mapped test source: {test_path}")
    if errors:
        raise SystemExit("AuthBus implementation-map source validation failed:\n" + "\n".join(errors))


def document(source_commit: str) -> dict[str, Any]:
    source_tree = run("git", "rev-parse", f"{source_commit}^{{tree}}")
    operations: list[dict[str, Any]] = []
    for operation in OPERATIONS:
        mapped = dict(operation)
        mapped["tests"] = [{"path": path, "symbol": symbol} for path, symbol in operation["tests"]]
        mapped.update(
            {
                "designOperation": operation["operation"],
                "mappingClass": "owner_native",
                "delegatedCallees": [],
                "sourcePathExists": True,
                "sourceBlob": source_blob(source_commit, operation["sourcePath"]),
            }
        )
        operations.append(mapped)
    return {
        "schema": "hepta.module-implementation-map.v3",
        "schemaVersion": 3,
        "sourceBase": {"commit": source_commit, "tree": source_tree},
        "sourceBaseRole": "newest_commit_touching_declared_authbus_source_roots",
        "laneId": "LANE-A-FOUNDATION",
        "module": "auth.authbus",
        "owner": "identity-access",
        "deputy": "security-authority",
        "technicalGuide": "docs/modules/auth.authbus/TECHNICAL.md",
        "currentImplementation": "docs/lane-a-foundation/auth.authbus/CURRENT_IMPLEMENTATION.md",
        "generatedBy": "scripts/generate-authbus-implementation-map.py",
        "declaredRoots": SOURCE_ROOTS,
        "resolvedRoots": SOURCE_ROOTS,
        "sourceRoot": SOURCE_ROOTS,
        "sourceRootPresent": True,
        "productionImplementation": False,
        "productCallerState": "source_composed_agentd_and_bao_not_activated",
        "productionWriterState": "source_implemented_single_owner_not_activated",
        "operations": operations,
        "operationalDocuments": [
            "docs/modules/auth.authbus/THREAT_MODEL.md",
            "docs/modules/auth.authbus/OPERATIONS.md",
            "docs/modules/auth.authbus/SLO.md",
            "docs/modules/auth.authbus/RECOVERY.md",
            "docs/modules/auth.authbus/KEY_ROTATION.md",
            "docs/modules/auth.authbus/SCHEMA_COMPATIBILITY.md",
            "docs/modules/auth.authbus/PROVIDER_AND_DEPLOYMENT.md",
            "docs/modules/auth.authbus/DASHBOARD.json",
            "docs/modules/auth.authbus/ALERTS.json",
            "docs/modules/auth.authbus/PUBLIC_API_INVENTORY.json",
        ],
        "repositoryControlledGaps": [
            "Obtain terminal-success exact-head and deterministic synthetic-merge receipts for one unchanged candidate.",
            "Complete target-host ENOSPC, power-loss, KMS/HSM and operator acceptance evidence.",
        ],
        "externalEvidenceGates": [
            "independent semantic and security review",
            "target-host qualification",
            "operator acceptance, canary, promotion and release",
        ],
        "claimBoundary": {
            "nativeSourceMappingComplete": True,
            "sourceRootPresent": True,
            "productionImplementation": False,
            "productSourceComposition": True,
            "productExecutionProved": False,
            "independentAcceptance": False,
            "activation": False,
            "release": False,
            "implementedOperationMappingComplete": True,
        },
        "exactHeadQualificationPolicy": {
            "state": "external_exact_candidate_receipt_required",
            "verifier": "scripts/authbus-exact-head-evidence.py",
            "sourceInventoryVerifier": "scripts/check-authbus-closed-world.py --check",
            "implementationMapVerifier": "scripts/generate-authbus-implementation-map.py --check",
            "workflows": [
                ".github/workflows/authbus-authority-qualification.yml",
                ".github/workflows/hepta-consolidated-source.yml",
            ],
            "successRule": "source-head and synthetic-merge jobs must both reach terminal success; queued, skipped or cancelled is not success",
        },
    }


def encoded(value: dict[str, Any]) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true")
    group.add_argument("--check", action="store_true")
    args = parser.parse_args()
    validate_sources()

    newest = latest_source_commit()
    if args.write:
        MAP_PATH.write_text(encoded(document(newest)), encoding="utf-8")
        return

    if not MAP_PATH.is_file():
        raise SystemExit("missing AuthBus implementation map")
    current = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    anchored = current.get("sourceBase", {}).get("commit")
    if anchored != newest:
        raise SystemExit(
            f"AuthBus implementation map is stale: sourceBase={anchored}, newestSourceCommit={newest}"
        )
    expected = encoded(document(newest))
    if MAP_PATH.read_text(encoding="utf-8") != expected:
        raise SystemExit(
            "AuthBus implementation map content is stale; run scripts/generate-authbus-implementation-map.py --write"
        )


if __name__ == "__main__":
    main()
