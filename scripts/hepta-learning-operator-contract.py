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
    match = re.search(
        rf"pub const {re.escape(name)}:\s*u32\s*=\s*(\d+)\s*;", read(path)
    )
    require(match is not None, f"{path} missing public u32 constant {name}")
    return int(match.group(1))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def require_sha(value: object, label: str) -> None:
    require(
        isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) is not None,
        label,
    )


def reject_legacy_source_commit(value: object, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            require(key != "sourceCommit", f"{path}.sourceCommit is forbidden")
            reject_legacy_source_commit(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_legacy_source_commit(child, f"{path}[{index}]")


def verify_receipt() -> None:
    receipt_path = ROOT / "qualification/lane-e/learning-operator-qualification-manifest.json"
    require(receipt_path.exists(), "qualification manifest absent")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    reject_legacy_source_commit(receipt)
    require(
        receipt.get("schema") == "hepta.learning-operator-qualification-manifest.v2"
        and receipt.get("schemaVersion") == 2,
        "qualification manifest schema",
    )
    source = receipt.get("source", {})
    require_sha(source.get("sha"), "source SHA")
    require_sha(source.get("tree"), "source tree")
    require_sha(receipt.get("workflow", {}).get("blobSha"), "workflow blob SHA")
    require_sha(receipt.get("currentMain", {}).get("sha"), "current main SHA")
    require_sha(receipt.get("syntheticMerge", {}).get("sha"), "synthetic merge SHA")
    require_sha(receipt.get("syntheticMerge", {}).get("tree"), "synthetic merge tree")
    require(
        isinstance(receipt.get("dependencyLock", {}).get("sha256"), str)
        and len(receipt["dependencyLock"]["sha256"]) == 64,
        "lock digest",
    )
    require(
        receipt.get("independentAcceptanceIdentity") is None,
        "independent acceptance must remain externally unissued",
    )
    require(
        receipt.get("externalGates", {}).get("status") == "unissued_external_gate",
        "external gate status",
    )
    for key in (
        "independentScientificAcceptance",
        "targetHostBenchmarkAcceptance",
        "futureWindowEfficacy",
        "operatorAcceptance",
        "canaryAcceptance",
        "promotion",
        "activation",
        "release",
    ):
        require(receipt["externalGates"].get(key) is False, f"external gate {key}")

    implementation = receipt.get("implementationMap", {})
    map_path = ROOT / implementation.get("path", "")
    require(map_path.is_file(), "current implementation map absent")
    require(sha256(map_path) == implementation.get("sha256"), "implementation map digest")
    map_value = json.loads(map_path.read_text(encoding="utf-8"))
    reject_legacy_source_commit(map_value)
    require(
        map_value.get("source") == {"sha": source["sha"], "tree": source["tree"]},
        "implementation map source identity",
    )
    require(
        implementation.get("sourceSha") == source["sha"]
        and implementation.get("sourceTree") == source["tree"],
        "manifest implementation-map source identity",
    )

    required = {
        "documentation-map",
        "exact-head",
        "lifecycle-state-space",
        "module-tests",
        "payload-replay",
        "performance-profile",
        "synthetic-merge",
        "target-build",
        "workspace-all-targets",
    }
    evidence = receipt.get("evidence")
    require(isinstance(evidence, list), "evidence inventory")
    observed: set[str] = set()
    for entry in evidence:
        require(isinstance(entry, dict), "evidence entry")
        name = entry.get("name")
        evidence_path = ROOT / entry.get("path", "")
        require(isinstance(name, str) and name not in observed, "unique evidence name")
        require(evidence_path.is_file(), f"{name}: evidence file absent")
        require(sha256(evidence_path) == entry.get("sha256"), f"{name}: evidence digest")
        gate = json.loads(evidence_path.read_text(encoding="utf-8"))
        require(
            gate.get("module") == "learning.operator"
            and gate.get("sourceSha") == source["sha"]
            and gate.get("sourceTree") == source["tree"]
            and gate.get("status") == "pass",
            f"{name}: source-bound pass receipt",
        )
        observed.add(name)
    require(required.issubset(observed), "required evidence gates")

    aggregate = receipt.pop("aggregateEvidenceSha256", None)
    require(
        aggregate == hashlib.sha256(canonical_bytes(receipt)).hexdigest(),
        "aggregate evidence digest",
    )
    receipt["aggregateEvidenceSha256"] = aggregate


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
    require(versions["V4"]["productionAllowed"], "V4 production qualification path")

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
            "OfflineIntegrityCandidateV1",
            "verify_offline_tabular_integrity_v1",
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
        "LoadedTabularOperatorV1"
        not in read("codex-rs/hepta-agentd/src/shared_terminal_cell.rs"),
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
            "VerifiedUsableCandidate",
            "self.model.revalidate(&current)",
            "terminal_close",
            "whole_batch_abstains",
        ],
    )
    require_tokens(
        "codex-rs/hepta-agentd/src/cognitive_ranker_admission.rs",
        [
            "pub struct VerifiedUsableCandidate",
            "fn new(",
            "fn predict_after_current_validation",
            "now_unix_micros",
            "clock moved backwards",
        ],
    )
    require_tokens(
        "codex-rs/hepta-agentd/src/cognitive_ranker_reload.rs",
        ["ArcSwap", "ReloadableCognitiveRanker"],
    )
    require_tokens(
        "codex-rs/hepta-agentd/src/learning_operator_coordinator.rs",
        [
            "coordinate_learning_operator_run_v1",
            "freeze_training",
            "freeze_evaluation",
            "evaluation_dataset.dataset_digest == training.dataset_digest",
            "LearningOperatorRollbackTriggerV1",
            "expected_authority_epoch",
        ],
    )
    require_tokens(
        "codex-rs/hepta-agentd/src/lib.rs",
        [
            "mod learning_operator_coordinator;",
            "VerifiedUsableCandidate",
            "LearningOperatorCoordinatorPortsV1",
            "coordinate_learning_operator_run_v1",
        ],
    )
    for script_path in (
        "scripts/hepta-learning-operator-evidence.py",
        "scripts/hepta-learning-operator-map.py",
        "scripts/hepta-learning-operator-receipt.py",
    ):
        require((ROOT / script_path).is_file(), f"{script_path} absent")

    docs = [
        "docs/modules/learning.operator/TECHNICAL.md",
        "qualification/module-execution-dossiers/detail/learning.operator.md",
        "codex-rs/hepta-bellman-operator/NATIVE_MAPPING.md",
        "docs/modules/learning.operator/ADMISSION_CONTRACT.md",
        "docs/modules/learning.operator/COMPATIBILITY_RESOURCE_AND_SHADOW_POLICY.md",
        "docs/modules/learning.operator/OPERATIONS_RUNBOOK.md",
    ]
    for doc_path in docs:
        require_tokens(
            doc_path,
            [
                "DatasetSnapshotReceiptV4",
                "TabularPayloadPinV2",
                "LoadedTabularOperatorV2",
            ],
        )
    require_tokens(
        "docs/modules/learning.operator/ADMISSION_CONTRACT.md",
        compatibility["productionPath"]["typeState"]
        + ["VerifiedUsableCandidate", "trusted time"],
    )
    require_tokens(
        "docs/modules/learning.operator/COMPATIBILITY_RESOURCE_AND_SHADOW_POLICY.md",
        ["V1", "V2", "V3", "V4", "WorldModelArtifactV2", "performance profile"],
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
            "crash during publication",
        ],
    )

    implementation = json.loads(
        read("docs/modules/learning.operator/IMPLEMENTATION_MAP.json")
    )
    reject_legacy_source_commit(implementation)
    operations = {row["operation"] for row in implementation["operations"]}
    for operation in {
        "build_sensor_core_v2",
        "verify_tabular_operator_plan_v4",
        "fit_tabular_operator_verified_v4",
        "verify_world_model_plan_v4",
        "fit_world_model_verified_v4",
        "load_pinned_tabular_operator_v2",
        "concurrent_current_candidate_use",
        "coordinate_learning_operator_run_v1",
        "load_verified_usable_candidate",
        "verify_offline_tabular_integrity_v1",
        "generate_current_implementation_map",
        "emit_qualification_manifest_v2",
    }:
        require(operation in operations, f"implementation map missing {operation}")
    boundary = implementation["claimBoundary"]
    require(
        boundary.get("boundedCoordinatorImplemented") is True,
        "bounded coordinator status",
    )
    require(
        boundary.get("atomicVerifiedUseImplemented") is True,
        "atomic verified-use status",
    )
    require(
        not boundary["independentAcceptance"],
        "repository cannot self-issue acceptance",
    )
    require(not boundary["activation"], "qualification change cannot activate")
    require(not boundary["release"], "qualification change cannot release")

    if require_receipt:
        verify_receipt()

    print("learning.operator source/schema/document contract verified")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["verify"])
    parser.add_argument("--require-receipt", action="store_true")
    args = parser.parse_args()
    verify(args.require_receipt)


if __name__ == "__main__":
    main()
