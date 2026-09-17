#!/usr/bin/env python3
"""One-shot formatter/registry synchronizer for the durable kernel.operations branch."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DURABILITY = "sqlite_wal_full_sync"
IMPLEMENTATION = "sqlite_durable_store_with_reference_model"
ACTIVATION = "host_composition_required"


def load(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def dump(path: str, value, *, compact: bool = False):
    target = ROOT / path
    if compact:
        text = json.dumps(value, separators=(",", ":"), ensure_ascii=False) + "\n"
    else:
        text = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    target.write_text(text, encoding="utf-8")


def module(rows, name: str):
    return next(row for row in rows if row.get("module") == name or row.get("id") == name)


def replace_once(path: str, old: str, new: str):
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise RuntimeError(f"expected exactly one replacement in {path}: {old[:80]!r}")
    target.write_text(text.replace(old, new), encoding="utf-8")


def capability(
    capability_id: str,
    summary: str,
    public_symbols: list[str],
    source_evidence: list[dict],
    positive_tests: list[dict],
    negative_tests: list[dict],
):
    return {
        "capabilityId": capability_id,
        "module": "kernel.operations",
        "summary": summary,
        "publicSymbols": public_symbols,
        "sourceEvidence": source_evidence,
        "positiveTests": positive_tests,
        "negativeTests": negative_tests,
        "durability": DURABILITY,
        "activation": ACTIVATION,
        "productionCaller": None,
        "receiptStatus": "native_workflow_required",
    }


def update_matrix():
    value = load("docs/lane-a-foundation/MODULE_TRUTH_MATRIX.json")
    row = module(value["modules"], "kernel.operations")
    row["profile"] = "durable_operation_store_with_reference_oracle"
    row["implementationDetail"] = "docs/lane-a-foundation/kernel.operations/DURABLE_STORE_V1.md"
    row["states"] = {
        "source": "implemented",
        "implementation": IMPLEMENTATION,
        "durability": DURABILITY,
        "qualification": "durable_fault_and_model_tests_present",
        "activation": ACTIVATION,
        "acceptance": "not_granted",
    }
    row["currentCapabilities"] = [
        "bounded deterministic operation-state reference model",
        "atomic SQLite durable operation ledger and transactional cross-owner outbox",
        "lease-fenced crash-reopen recovery that blocks blind retry after unknown effects",
        "final-use authority dispatch with generation-fenced terminal reconciliation",
        "destination-owned transactional effect deduplication",
    ]
    row["targetOnlyCapabilities"] = [
        "named production caller and selected host lifecycle",
        "target-host power-loss and real disk-full qualification",
        "host-owned background dispatcher and reconciler process",
        "asynchronous final-use authority boundary",
        "external monotonic anti-rollback checkpoint when required by product policy",
    ]
    row["sourceAnchors"] = [
        {
            "path": "codex-rs/hepta-operations/src/durable.rs",
            "mustContain": [
                "pub struct DurableOperationStore",
                "SqliteJournalMode::Wal",
                "SqliteSynchronous::Full",
                'begin_with("BEGIN IMMEDIATE")',
                "RequiresReconciliation",
            ],
        },
        {
            "path": "codex-rs/hepta-operations/src/dispatcher.rs",
            "mustContain": [
                "pub struct DurableDispatcher",
                "DestinationEffectAdapter",
                "with_verified_use",
            ],
        },
        {
            "path": "codex-rs/hepta-operations/src/destination_dedupe.rs",
            "mustContain": [
                "DESTINATION_DEDUPE_SCHEMA_V1",
                "reserve_destination_effect",
                "finish_destination_effect",
            ],
        },
        {
            "path": "codex-rs/hepta-operations/migrations/0001_durable_operations.sql",
            "mustContain": [
                "CREATE TABLE operation_ledger",
                "CREATE TABLE cross_owner_outbox",
                "FOREIGN KEY(scope_id, operation_id)",
            ],
        },
        {
            "path": "codex-rs/hepta-operations/src/model.rs",
            "mustContain": [
                "pub struct ReferenceAuthorityWitness",
                "not a cryptographic credential",
            ],
        },
    ]
    dump("docs/lane-a-foundation/MODULE_TRUTH_MATRIX.json", value)


def update_capability_map():
    value = load("docs/lane-a-foundation/CAPABILITY_EVIDENCE_MAP.json")
    entries = value["entries"]
    first = next(i for i, row in enumerate(entries) if row["module"] == "kernel.operations")
    entries = [row for row in entries if row["module"] != "kernel.operations"]
    new = [
        capability(
            "kernel.operations.reference-oracle.v1",
            "bounded deterministic operation-state reference model",
            ["OperationLedger", "OperationState", "ReferenceAuthorityWitness"],
            [
                {"path": "codex-rs/hepta-operations/src/ledger.rs", "mustContain": ["MAX_MODEL_OPERATION_RECORDS", "pub struct OperationLedger"]},
                {"path": "codex-rs/hepta-operations/src/model.rs", "mustContain": ["pub enum OperationState", "ReferenceAuthorityWitness"]},
            ],
            [{"path": "codex-rs/hepta-operations/src/ledger_tests.rs", "mustContain": ["exact_command_replay_is_idempotent_within_the_reference_model"]}],
            [{"path": "codex-rs/hepta-operations/src/ledger_tests.rs", "mustContain": ["zero_digests_reject_without_mutation", "reference_ledger_capacity_is_bounded"]}],
        ),
        capability(
            "kernel.operations.atomic-durable-store.v1",
            "atomic SQLite durable operation ledger and transactional cross-owner outbox",
            ["DurableOperationStore", "DurableIntent", "OperationIdentity"],
            [
                {"path": "codex-rs/hepta-operations/src/durable.rs", "mustContain": ["pub struct DurableOperationStore", 'begin_with("BEGIN IMMEDIATE")', "prepare_intent"]},
                {"path": "codex-rs/hepta-operations/migrations/0001_durable_operations.sql", "mustContain": ["CREATE TABLE operation_ledger", "CREATE TABLE cross_owner_outbox"]},
            ],
            [{"path": "codex-rs/hepta-operations/src/durable_tests.rs", "mustContain": ["prepare_commits_ledger_and_outbox_atomically"]}],
            [{"path": "codex-rs/hepta-operations/src/durable_tests.rs", "mustContain": ["test_fail_outbox", "payload_drift_conflicts"]}],
        ),
        capability(
            "kernel.operations.crash-reopen-fence.v1",
            "lease-fenced crash-reopen recovery that blocks blind retry after unknown effects",
            ["DispatchLease", "DurableOperationStore::claim_outbox", "DurableOperationStore::recover_expired_leases"],
            [{"path": "codex-rs/hepta-operations/src/durable.rs", "mustContain": ["pub struct DispatchLease", "recover_expired_leases", "mark_recovery_indeterminate"]}],
            [{"path": "codex-rs/hepta-operations/src/durable_tests.rs", "mustContain": ["expired_pre_dispatch_lease_can_be_taken_over_by_new_generation"]}],
            [{"path": "codex-rs/hepta-operations/src/durable_tests.rs", "mustContain": ["reopen_after_dispatch_never_blindly_requeues_unknown_effect", "RequiresReconciliation"]}],
        ),
        capability(
            "kernel.operations.final-use-reconciliation.v1",
            "final-use authority dispatch with generation-fenced terminal reconciliation",
            ["DurableDispatcher", "DispatchResult", "DurableOperationStore::observe_terminal"],
            [{"path": "codex-rs/hepta-operations/src/dispatcher.rs", "mustContain": ["pub struct DurableDispatcher", "with_verified_use", "SignedFinalUseGrant"]}],
            [{"path": "codex-rs/hepta-operations/src/durable_tests.rs", "mustContain": ["dispatcher_consumes_real_final_use_authority_at_effect_boundary"]}],
            [{"path": "codex-rs/hepta-operations/src/durable_tests.rs", "mustContain": ["acknowledgement_loss_stays_indeterminate_until_authoritative_observation"]}],
        ),
        capability(
            "kernel.operations.destination-dedupe.v1",
            "destination-owned transactional effect deduplication",
            ["DestinationDedupeKey", "reserve_destination_effect", "finish_destination_effect"],
            [{"path": "codex-rs/hepta-operations/src/destination_dedupe.rs", "mustContain": ["DESTINATION_DEDUPE_SCHEMA_V1", "reserve_destination_effect", "finish_destination_effect"]}],
            [{"path": "codex-rs/hepta-operations/src/durable_tests.rs", "mustContain": ["destination_dedupe_commits_with_destination_transaction", "AlreadyApplied"]}],
            [{"path": "codex-rs/hepta-operations/src/destination_dedupe.rs", "mustContain": ["semantic_digest != key.semantic_digest", "DurableOperationError::Conflict"]}],
        ),
    ]
    value["entries"] = entries[:first] + new + entries[first:]
    value["entryCount"] = len(value["entries"])
    dump("docs/lane-a-foundation/CAPABILITY_EVIDENCE_MAP.json", value, compact=True)


def update_protocol_registry():
    value = load("docs/lane-a-foundation/PROTOCOL_REGISTRY_V1.json")
    row = module(value["protocols"], "kernel.operations")
    row["protocolId"] = "hepta.kernel.operations.durable-store.v1"
    row["kind"] = "sqlite_durable_operation_ledger_transactional_outbox"
    row["source"] = [
        "codex-rs/hepta-operations/src/durable.rs",
        "codex-rs/hepta-operations/src/dispatcher.rs",
        "codex-rs/hepta-operations/src/destination_dedupe.rs",
        "codex-rs/hepta-operations/migrations/0001_durable_operations.sql",
        "codex-rs/hepta-operations/src/ledger.rs",
    ]
    row["invariants"] = [
        "operation intent and local outbox publication commit in one SQLite IMMEDIATE transaction",
        "WAL FULL-sync store open verifies migration objects quick-check and foreign keys",
        "claims are bounded by monotonic fence attempt owner-generation and lease deadline",
        "expired pre-dispatch claims may be taken over but post-dispatch uncertainty becomes indeterminate",
        "transport acknowledgement is never terminal success and terminal observation is generation fenced",
        "real final-use authority is consumed immediately at synchronous adapter entry",
        "destination dedupe runs inside the destination owner's transaction and kernel.operations never directly writes its domain store",
        "the bounded in-memory reference model remains an independent transition oracle",
    ]
    dump("docs/lane-a-foundation/PROTOCOL_REGISTRY_V1.json", value)


def update_module_registry():
    value = load("docs/modules/MODULES.json")
    row = next(row for row in value["modules"] if row["id"] == "kernel.operations")
    row["uses"] = ["platform.types", "kernel.authority"]
    # The durable source exists, but product composition/activation is still a separate gate.
    row["production_implementation"] = False
    dump("docs/modules/MODULES.json", value)


def update_native_binding():
    value = load("qualification/module-execution-dossiers/NATIVE_BINDINGS_LANE_A.json")
    row = module(value["observations"], "kernel.operations")
    row["path"] = "codex-rs/hepta-operations/src/durable.rs"
    row["blobSha"] = "c7302a34146b688f782fe88b2cfc13f1c3419a76"
    row["exports"] = [
        "DurableOperationStore",
        "DurableIntent",
        "prepare_intent",
        "claim_outbox",
        "observe_terminal",
        "recover_expired_leases",
    ]
    encoded = json.dumps(
        value["observations"], sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    value["sourceObservationDigest"] = hashlib.sha256(encoded).hexdigest()
    dump("qualification/module-execution-dossiers/NATIVE_BINDINGS_LANE_A.json", value)


def update_implementation_map():
    value = load("docs/modules/kernel.operations/IMPLEMENTATION_MAP.json")
    value["productionImplementation"] = False
    value["productCallerState"] = "not_composed"
    value["productionWriterState"] = "durable_store_implemented_not_product_composed"
    value["operations"] = [
        {
            "operation": "durableoperationstore",
            "nativeSymbol": "DurableOperationStore",
            "sourcePath": "codex-rs/hepta-operations/src/durable.rs",
            "state": "source_implemented_not_product_composed",
            "authority": "kernel.authority_final_use_required_at_dispatch",
            "tests": ["codex-rs/hepta-operations/src/durable_tests.rs"],
            "sourcePathExists": True,
            "designOperation": "operationledger",
            "mappingClass": "owner_native",
            "delegatedCallees": [],
        },
        {
            "operation": "durabledispatcher",
            "nativeSymbol": "DurableDispatcher",
            "sourcePath": "codex-rs/hepta-operations/src/dispatcher.rs",
            "state": "source_implemented_not_product_composed",
            "authority": "kernel.authority_final_use",
            "tests": ["codex-rs/hepta-operations/src/durable_tests.rs"],
            "sourcePathExists": True,
            "designOperation": "claim_outbox",
            "mappingClass": "owner_native",
            "delegatedCallees": [],
        },
        {
            "operation": "operationledger_reference_oracle",
            "nativeSymbol": "OperationLedger",
            "sourcePath": "codex-rs/hepta-operations/src/ledger.rs",
            "state": "reference_oracle_implemented",
            "authority": "none",
            "tests": ["codex-rs/hepta-operations/src/ledger_tests.rs"],
            "sourcePathExists": True,
            "designOperation": "operationledger",
            "mappingClass": "owner_native_reference",
            "delegatedCallees": [],
        },
        {
            "operation": "outbox_reference_oracle",
            "nativeSymbol": "Outbox",
            "sourcePath": "codex-rs/hepta-operations/src/outbox.rs",
            "state": "reference_oracle_implemented",
            "authority": "none",
            "tests": ["codex-rs/hepta-operations/src/outbox_tests.rs"],
            "sourcePathExists": True,
            "designOperation": "outbox",
            "mappingClass": "owner_native_reference",
            "delegatedCallees": [],
        },
    ]
    value["repositoryControlledGaps"] = [
        "Bind a named authenticated product caller and selected durable-store path.",
        "Install the destination dedupe table/helper in the actual destination owner's transaction.",
        "Run exact-head and deterministic synthetic-merge tests before changing the claim boundary.",
    ]
    boundary = value.setdefault("claimBoundary", {})
    boundary.update(
        {
            "nativeSourceMappingComplete": True,
            "sourceRootPresent": True,
            "productionImplementation": False,
            "productExecutionProved": False,
            "independentAcceptance": False,
            "activation": False,
            "release": False,
        }
    )
    dump("docs/modules/kernel.operations/IMPLEMENTATION_MAP.json", value)


def update_verifiers():
    replace_once(
        "scripts/lane_a_foundation_lib.py",
        '("kernel.operations", "implementation"): "bounded_reference_model",\n        ("kernel.operations", "durability"): "not_implemented",',
        f'("kernel.operations", "implementation"): "{IMPLEMENTATION}",\n        ("kernel.operations", "durability"): "{DURABILITY}",',
    )
    replace_once(
        "scripts/lane_a_foundation_core.py",
        '"codex-rs/hepta-operations/src/lib.rs": [\n            "In-memory reference model",\n            "does not provide durable storage",\n        ],',
        '"codex-rs/hepta-operations/src/lib.rs": [\n            "pub use durable::DurableOperationStore;",\n            "pub use dispatcher::DurableDispatcher;",\n        ],\n        "codex-rs/hepta-operations/src/durable.rs": [\n            "SqliteJournalMode::Wal",\n            "SqliteSynchronous::Full",\n            \'begin_with("BEGIN IMMEDIATE")\',\n            "RequiresReconciliation",\n        ],\n        "codex-rs/hepta-operations/src/dispatcher.rs": [\n            "SignedFinalUseGrant",\n            "with_verified_use",\n            "DestinationEffectAdapter",\n        ],',
    )


def update_technical_guide():
    path = "docs/modules/kernel.operations/TECHNICAL.md"
    replace_once(
        path,
        "The registered primary source is [codex-rs/hepta-operations/src/ledger.rs](../../../codex-rs/hepta-operations/src/ledger.rs); observed identifiers include `MAX_MODEL_OPERATION_RECORDS`, `OperationLedger`, `begin`, `authorize`, `record_dispatch`, `mark_indeterminate`. This is a source navigation binding, not proof that every target operation or production consumer exists. Read the [current native implementation](../../../qualification/module-execution-dossiers/detail/kernel.operations.md#8-current-native-implementation) alongside the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/kernel.operations.md) for the implemented subset and remaining product work.",
        "The registered durable source is [codex-rs/hepta-operations/src/durable.rs](../../../codex-rs/hepta-operations/src/durable.rs); observed identifiers include `DurableOperationStore`, `prepare_intent`, `claim_outbox`, `recover_expired_leases` and `observe_terminal`. The final-use adapter is [src/dispatcher.rs](../../../codex-rs/hepta-operations/src/dispatcher.rs), while `OperationLedger`/`Outbox` remain deterministic reference oracles. This is source implementation evidence, not proof of a product caller, activation or external acceptance. Read the [current native implementation](../../../qualification/module-execution-dossiers/detail/kernel.operations.md#8-current-native-implementation) and [durable store reference](../../lane-a-foundation/kernel.operations/DURABLE_STORE_V1.md) together.",
    )
    replace_once(
        path,
        "Direct dependencies:\n\n- `platform.types`",
        "Direct dependencies:\n\n- `platform.types`\n- `kernel.authority`",
    )
    replace_once(
        path,
        "A source library or fixture cannot stand in for an unimplemented durable recovery or external reconciler.",
        "The checked-in SQLite owner supplies durable recovery; target-host process/power-loss evidence and each actual external terminal observer remain separate composition and qualification obligations.",
    )
    replace_once(
        path,
        "Current native limits belong to [codex-rs/hepta-operations/src/ledger.rs](../../../codex-rs/hepta-operations/src/ledger.rs) and the linked implementation components.",
        "Current durable limits are enforced by `MAX_DURABLE_OPERATION_ROWS`, `MAX_DURABLE_OUTBOX_ROWS`, `MAX_DURABLE_CLAIM_BATCH`, bounded attempts, lease duration and retry delay in [src/durable.rs](../../../codex-rs/hepta-operations/src/durable.rs); the 16,384-record reference limits remain oracle-only.",
    )
    replace_once(
        path,
        "OperationLedger and outbox types are embedded owner components. Their state transition result is not a remote effect observation. The host must bind each durable destination/outbox and current-fence reconciler; an in-memory ledger does not supply crash durability by itself.",
        "`DurableOperationStore` is the authoritative local owner for the operation ledger and source outbox. Its state transition is still not a remote-effect observation: the host must bind the actual destination-owned dedupe transaction and trusted terminal observer. `OperationLedger` and `Outbox` remain in-memory reference oracles only.",
    )
    replace_once(
        path,
        "- [codex-rs/hepta-operations/src/ledger.rs](../../../codex-rs/hepta-operations/src/ledger.rs).\n- [codex-rs/hepta-operations/src/outbox.rs](../../../codex-rs/hepta-operations/src/outbox.rs).",
        "- [codex-rs/hepta-operations/src/durable.rs](../../../codex-rs/hepta-operations/src/durable.rs).\n- [codex-rs/hepta-operations/src/dispatcher.rs](../../../codex-rs/hepta-operations/src/dispatcher.rs).\n- [codex-rs/hepta-operations/migrations/0001_durable_operations.sql](../../../codex-rs/hepta-operations/migrations/0001_durable_operations.sql).\n- [docs/lane-a-foundation/kernel.operations/DURABLE_STORE_V1.md](../../lane-a-foundation/kernel.operations/DURABLE_STORE_V1.md).",
    )
    replace_once(
        path,
        "- [codex-rs/hepta-operations/src/ledger_tests.rs](../../../codex-rs/hepta-operations/src/ledger_tests.rs); named case: `dispatch_ack_is_not_terminal_success`.\n- [codex-rs/hepta-operations/src/outbox_tests.rs](../../../codex-rs/hepta-operations/src/outbox_tests.rs); named case: `claim_and_ack_are_generation_fenced`.",
        "- [codex-rs/hepta-operations/src/durable_tests.rs](../../../codex-rs/hepta-operations/src/durable_tests.rs); named cases: `prepare_commits_ledger_and_outbox_atomically`, `reopen_after_dispatch_never_blindly_requeues_unknown_effect`, `dispatcher_consumes_real_final_use_authority_at_effect_boundary`.\n- [codex-rs/hepta-operations/src/ledger_tests.rs](../../../codex-rs/hepta-operations/src/ledger_tests.rs); named case: `dispatch_ack_is_not_terminal_success`.\n- [codex-rs/hepta-operations/src/outbox_tests.rs](../../../codex-rs/hepta-operations/src/outbox_tests.rs); named case: `claim_and_ack_are_generation_fenced`.",
    )
    replace_once(
        path,
        "| `operationledger` | `OperationLedger` | `codex-rs/hepta-operations/src/ledger.rs` | `pending` |\n| `outbox` | `Outbox` | `codex-rs/hepta-operations/src/outbox.rs` | `pending` |",
        "| `durableoperationstore` | `DurableOperationStore` | `codex-rs/hepta-operations/src/durable.rs` | `durable_tests.rs` |\n| `durabledispatcher` | `DurableDispatcher` | `codex-rs/hepta-operations/src/dispatcher.rs` | `durable_tests.rs` |\n| `operationledger_reference_oracle` | `OperationLedger` | `codex-rs/hepta-operations/src/ledger.rs` | `ledger_tests.rs` |\n| `outbox_reference_oracle` | `Outbox` | `codex-rs/hepta-operations/src/outbox.rs` | `outbox_tests.rs` |",
    )
    replace_once(
        path,
        "- Consumer callsites and durable owner stores remain an explicit follow-up when not listed above.\n- Production implementation, runtime composition, independent acceptance, activation, and release remain false until their separate evidence gates pass.",
        "- The durable owner store is implemented; a named product caller and destination-owned dedupe migration remain explicit composition follow-ups.\n- Product execution, independent acceptance, activation, and release remain false until their separate evidence gates pass.",
    )


def add_destination_negative_fixture():
    path = ROOT / "codex-rs/hepta-operations/src/durable_tests.rs"
    text = path.read_text(encoding="utf-8")
    marker = '    replay.commit().await.expect("replay commit");\n}'
    addition = '''    replay.commit().await.expect("replay commit");

    let changed = DestinationDedupeKey {
        semantic_digest: Digest32::of_bytes(b"changed-semantics"),
        ..key.clone()
    };
    let mut conflict = pool.begin_with("BEGIN IMMEDIATE").await.expect("conflict tx");
    assert!(matches!(
        reserve_destination_effect(&mut conflict, &changed, 4).await,
        Err(DurableOperationError::Conflict(_))
    ));
    conflict.rollback().await.expect("rollback conflict");
}'''
    if text.count(marker) != 1:
        raise RuntimeError("destination replay insertion marker drift")
    path.write_text(text.replace(marker, addition), encoding="utf-8")


def main():
    update_matrix()
    update_capability_map()
    update_protocol_registry()
    update_module_registry()
    update_native_binding()
    update_implementation_map()
    update_verifiers()
    update_technical_guide()
    add_destination_negative_fixture()


if __name__ == "__main__":
    main()
