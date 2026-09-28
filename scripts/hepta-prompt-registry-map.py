
#!/usr/bin/env python3
"""Generate the curated prompt.registry implementation claims before exact-blob materialization."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "docs/modules/prompt.registry/IMPLEMENTATION_MAP.json"
SOURCE_BASE = {
    "commit": "a126987b84737dbc2ee2592442a314117bddb4a2",
    "tree": "a22fd0074c45ae6f3cef2092cd6e273bf9c26c30",
}


def operation(
    name: str,
    symbol: str,
    source: str,
    authority: str,
    tests: list[str],
) -> dict:
    return {
        "operation": name,
        "nativeSymbol": symbol,
        "sourcePath": source,
        "state": "source_composed_product_activation_pending",
        "authority": authority,
        "tests": tests,
        "sourcePathExists": True,
        "designOperation": name,
        "mappingClass": "owner_native",
        "delegatedCallees": [],
    }


def main() -> None:
    row = json.loads(PATH.read_text(encoding="utf-8"))
    row.update(
        {
            "schema": "hepta.module-implementation-map.v3",
            "schemaVersion": 3,
            "sourceBase": SOURCE_BASE,
            "module": "prompt.registry",
            "sourceRootPresent": True,
            "productionImplementation": False,
            "productCallerState": "source_composed",
            "productionWriterState": "source_composed_authenticated_publisher",
            "schemaState": "strict_durable_v4",
            "activePersistentSchema": 4,
            "closedWorldPublicFunctions": False,
            "lifecycleStates": {
                "sourceImplemented": True,
                "sourceComposed": True,
                "productActivated": False,
                "accepted": False,
                "released": False,
            },
            "status": {
                "implemented": True,
                "composed": True,
                "qualified": False,
            },
            "productCallers": [
                {
                    "sourcePath": "codex-rs/hepta-agentd/src/prompt_pipeline.rs",
                    "state": "source_composed",
                },
                {
                    "sourcePath": "codex-rs/hepta-agentd/src/prompt_runtime.rs",
                    "state": "source_composed",
                },
                {
                    "sourcePath": "codex-rs/hepta-agentd/src/prompt_final_use.rs",
                    "state": "source_composed",
                },
                {
                    "sourcePath": "codex-rs/hepta-agentd/src/prompt_final_use_store.rs",
                    "state": "source_composed",
                },
            ],
        }
    )

    durable_tests = [
        "codex-rs/hepta-prompt-registry/src/durable.rs",
        "codex-rs/hepta-prompt-registry/src/durable_payloads_tests.rs::metadata_changes_never_rewrite_old_payloads_and_reopen_never_rewrites_manifest",
    ]
    maintenance_tests = [
        "codex-rs/hepta-prompt-registry/src/durable_maintenance.rs",
    ]
    row["operations"] = [
        operation(
            "open_state_dir",
            "DurablePromptRegistry::open_state_dir",
            "codex-rs/hepta-prompt-registry/src/durable.rs",
            "exclusive_private_state_owner",
            durable_tests,
        ),
        operation(
            "register_factor_final_use",
            "DurablePromptRegistry::register_factor_final_use",
            "codex-rs/hepta-prompt-registry/src/durable.rs",
            "single_use_final_authority",
            ["codex-rs/hepta-prompt-registry/src/lib_tests.rs"],
        ),
        operation(
            "register_factor_relation_final_use",
            "DurablePromptRegistry::register_factor_relation_final_use",
            "codex-rs/hepta-prompt-registry/src/durable.rs",
            "single_use_final_authority",
            ["codex-rs/hepta-prompt-registry/src/lib_tests.rs"],
        ),
        operation(
            "admit_factor_final_use",
            "DurablePromptRegistry::admit_factor_final_use",
            "codex-rs/hepta-prompt-registry/src/durable.rs",
            "single_use_final_authority",
            ["codex-rs/hepta-prompt-registry/src/lib_tests.rs"],
        ),
        operation(
            "register_realization_payload_final_use_v2",
            "DurablePromptRegistry::register_realization_payload_final_use_v2",
            "codex-rs/hepta-prompt-registry/src/durable.rs",
            "single_use_final_authority",
            ["codex-rs/hepta-prompt-registry/src/v2_tests.rs"],
        ),
        operation(
            "read_compatible_v2",
            "DurablePromptRegistry::read_compatible_v2",
            "codex-rs/hepta-prompt-registry/src/durable.rs",
            "deny_all_read_receipt",
            ["codex-rs/hepta-prompt-registry/src/v2_tests.rs"],
        ),
        operation(
            "dereference_realization_v2",
            "DurablePromptRegistry::dereference_realization_v2",
            "codex-rs/hepta-prompt-registry/src/durable.rs",
            "deny_all_read_receipt",
            ["codex-rs/hepta-prompt-registry/src/v2_tests.rs"],
        ),
        operation(
            "operational_metrics",
            "DurablePromptRegistry::operational_metrics",
            "codex-rs/hepta-prompt-registry/src/durable_maintenance.rs",
            "exclusive_private_state_owner_read",
            maintenance_tests,
        ),
        operation(
            "export_consistent_checkpoint",
            "DurablePromptRegistry::export_consistent_checkpoint",
            "codex-rs/hepta-prompt-registry/src/durable_maintenance.rs",
            "exclusive_private_state_owner_copy",
            maintenance_tests,
        ),
        operation(
            "checkpoint_compacted",
            "DurablePromptRegistry::checkpoint_compacted",
            "codex-rs/hepta-prompt-registry/src/durable_maintenance.rs",
            "exclusive_private_state_owner_copy",
            maintenance_tests,
        ),
        operation(
            "verify_restore_checkpoint",
            "DurablePromptRegistry::verify_restore_checkpoint",
            "codex-rs/hepta-prompt-registry/src/durable_maintenance.rs",
            "exclusive_private_state_owner_reopen",
            maintenance_tests,
        ),
        operation(
            "probe_fsync",
            "DurablePromptRegistry::probe_fsync",
            "codex-rs/hepta-prompt-registry/src/durable_maintenance.rs",
            "private_filesystem_probe",
            maintenance_tests,
        ),
    ]
    row["repositoryControlledGaps"] = [
        "Require green exact-head and deterministic synthetic-merge qualification receipts for the current source candidate.",
        "Require protected postmerge checks before any production-ready statement.",
        "Checkpoint activation remains an external quiescent owner decision; copy-compaction never self-switches the live store.",
    ]
    row["externalEvidenceGates"] = [
        "independent semantic and security review",
        "deployed product activation and target-host qualification",
        "operator acceptance, canary, promotion and release",
    ]
    row["claimBoundary"] = {
        "nativeSourceMappingComplete": True,
        "sourceRootPresent": True,
        "productionImplementation": False,
        "productExecutionProved": False,
        "independentAcceptance": False,
        "activation": False,
        "release": False,
        "implementedOperationMappingComplete": True,
    }
    PATH.write_text(json.dumps(row, sort_keys=True, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
