#!/usr/bin/env python3
"""Verify learning.operator source/schema/document/qualification consistency."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"learning.operator contract verification failed: {message}")


def require_tokens(path: str, tokens: list[str]) -> None:
    text = read(path)
    for token in tokens:
        require(token in text, f"{path} missing {token!r}")


def rust_const(path: str, name: str) -> int:
    match = re.search(rf"pub const {re.escape(name)}:\s*u32\s*=\s*(\d+)\s*;", read(path))
    require(match is not None, f"{path} missing public u32 constant {name}")
    return int(match.group(1))


def verify(require_receipt: bool) -> None:
    compatibility = json.loads(
        read("docs/modules/learning.operator/SCHEMA_COMPATIBILITY.json")
    )
    require(compatibility["schemaVersion"] == 1, "compatibility schema version")
    require(
        compatibility["productionPath"]
        == {
            "datasetReceipt": "DatasetSnapshotReceiptV4",
            "tabularPin": "TabularPayloadPinV2",
            "tabularLoader": "LoadedTabularOperatorV2",
            "worldModelArtifact": "WorldModelArtifactV2",
            "typeState": [
                "RawRows",
                "StructurallyValidated",
                "SourceAuthenticated",
                "CurrentAtUse",
                "VerifiedTrainingInput",
                "ImmutableCandidate",
                "IndependentlyEvaluated",
                "SelectedOrRollbackAuthorized",
                "LoadedReadOnly",
            ],
        },
        "production path or type-state drift",
    )
    versions = {row["version"]: row for row in compatibility["versions"]}
    require(set(versions) == {"V1", "V2", "V3", "V4"}, "migration matrix versions")
    require(not versions["V1"]["productionAllowed"], "V1 must not be production")
    require(not versions["V2"]["productionAllowed"], "V2 rows must not be production")
    require(not versions["V3"]["productionAllowed"], "V3 rows must not be production")
    require(versions["V4"]["productionAllowed"], "V4 must be production qualification path")

    require(
        rust_const(
            "codex-rs/hepta-learning-ledger/src/dataset_receipt_v4.rs",
            "DATASET_SNAPSHOT_RECEIPT_SCHEMA_V4",
        )
        == 4,
        "DatasetSnapshotReceiptV4 schema constant",
    )
    require(
        rust_const(
            "codex-rs/hepta-bellman-operator/src/world_model_v2.rs",
            "WORLD_MODEL_ARTIFACT_SCHEMA_V2",
        )
        == 2,
        "WorldModelArtifactV2 schema constant",
    )

    require_tokens(
        "codex-rs/hepta-learning-ledger/src/lib.rs",
        [
            "mod dataset_receipt_v4;",
            "DatasetSnapshotReceiptV4",
            "DatasetFreezePlanV4",
            "freeze_dataset_from_ledger_v4",
        ],
    )
    require_tokens(
        "codex-rs/hepta-bellman-operator/src/lib.rs",
        [
            "mod budget;",
            "mod dataset_bound_v4;",
            "mod sensor_core_v2;",
            "mod tabular_v2;",
            "mod world_model_v2;",
            "verify_tabular_operator_plan_v4",
            "fit_tabular_operator_verified_v4",
            "verify_world_model_plan_v4",
            "fit_world_model_verified_v4",
            "TabularPayloadPinV2",
            "LoadedTabularOperatorV2",
        ],
    )
    operator_lib = read("codex-rs/hepta-bellman-operator/src/lib.rs")
    require(
        '#[cfg(feature = "qualification-unverified-input")]\npub use loaded::LoadedTabularOperatorV1;'
        in operator_lib,
        "V1 loader must be qualification-feature gated",
    )
    require(
        '#[cfg(feature = "qualification-unverified-input")]\npub use loaded::TabularPayloadPinV1;'
        in operator_lib,
        "V1 pin must be qualification-feature gated",
    )
    require(
        "LoadedTabularOperatorV1" not in read("codex-rs/hepta-agentd/src/shared_terminal_cell.rs"),
        "production Agentd shared terminal path still imports V1 loader",
    )
    require_tokens(
        "codex-rs/hepta-learning-artifacts/src/lib.rs",
        ["mod pinned_concurrent;", "ConcurrentRevalidatingCandidate"],
    )
    require_tokens(
        "codex-rs/hepta-agentd/src/cognitive_ranker.rs",
        [
            "ConcurrentRevalidatingCandidate",
            "CognitiveRankerMetricsSnapshotV1",
            "terminal_close",
            "whole_batch_abstains",
        ],
    )
    require_tokens(
        "codex-rs/hepta-agentd/src/cognitive_ranker_reload.rs",
        ["ArcSwap", "ReloadableCognitiveRanker"],
    )

    docs = [
        "docs/modules/learning.operator/TECHNICAL.md",
        "qualification/module-execution-dossiers/detail/learning.operator.md",
        "codex-rs/hepta-bellman-operator/NATIVE_MAPPING.md",
        "docs/modules/learning.operator/ADMISSION_CONTRACT.md",
        "docs/modules/learning.operator/COMPATIBILITY_RESOURCE_AND_SHADOW_POLICY.md",
        "docs/modules/learning.operator/OPERATIONS_RUNBOOK.md",
    ]
    for path in docs:
        require_tokens(
            path,
            [
                "DatasetSnapshotReceiptV4",
                "TabularPayloadPinV2",
                "LoadedTabularOperatorV2",
            ],
        )
    require_tokens(
        "docs/modules/learning.operator/ADMISSION_CONTRACT.md",
        compatibility["productionPath"]["typeState"],
    )
    require_tokens(
        "docs/modules/learning.operator/COMPATIBILITY_RESOURCE_AND_SHADOW_POLICY.md",
        ["V1", "V2", "V3", "V4", "WorldModelArtifactV2"],
    )
    require_tokens(
        "docs/modules/learning.operator/OPERATIONS_RUNBOOK.md",
        [
            "key rotation",
            "revocation",
            "clock regression",
            "registry unavailable",
            "canary",
            "emergency stop",
        ],
    )

    implementation = json.loads(read("docs/modules/learning.operator/IMPLEMENTATION_MAP.json"))
    operations = {row["operation"] for row in implementation["operations"]}
    for operation in {
        "build_sensor_core_v2",
        "verify_tabular_operator_plan_v4",
        "fit_tabular_operator_verified_v4",
        "verify_world_model_plan_v4",
        "fit_world_model_verified_v4",
        "load_pinned_tabular_operator_v2",
        "concurrent_current_candidate_use",
    }:
        require(operation in operations, f"implementation map missing {operation}")
    boundary = implementation["claimBoundary"]
    require(not boundary["independentAcceptance"], "repository cannot self-issue acceptance")
    require(not boundary["activation"], "qualification change cannot activate")
    require(not boundary["release"], "qualification change cannot release")

    if require_receipt:
        receipt_path = ROOT / "qualification/lane-e/learning-operator-qualification-manifest.json"
        require(receipt_path.exists(), "qualification manifest absent")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        require(receipt["schemaVersion"] == 1, "qualification manifest schema")
        require(len(receipt["source"]["sha"]) == 40, "source SHA")
        require(len(receipt["source"]["tree"]) == 40, "source tree")
        require(len(receipt["workflow"]["blobSha"]) == 40, "workflow blob SHA")
        require(len(receipt["dependencyLock"]["sha256"]) == 64, "lock digest")
        require(len(receipt["syntheticMerge"]["sha"]) == 40, "synthetic merge SHA")
        require(len(receipt["syntheticMerge"]["tree"]) == 40, "synthetic merge tree")
        require(len(receipt["testArtifact"]["sha256"]) == 64, "test artifact digest")
        require(
            receipt["independentAcceptanceIdentity"] is None,
            "independent acceptance must remain externally unissued",
        )
        require(
            receipt["externalGates"]["status"] == "unissued_external_gate",
            "external gate status",
        )
        summary_path = ROOT / receipt["testArtifact"]["path"]
        require(summary_path.exists(), "test artifact file missing")
        actual = hashlib.sha256(summary_path.read_bytes()).hexdigest()
        require(actual == receipt["testArtifact"]["sha256"], "test artifact digest mismatch")

    print("learning.operator source/schema/document contract verified")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["verify"])
    parser.add_argument("--require-receipt", action="store_true")
    args = parser.parse_args()
    verify(args.require_receipt)


if __name__ == "__main__":
    main()
