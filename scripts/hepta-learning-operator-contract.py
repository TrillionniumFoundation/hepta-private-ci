#!/usr/bin/env python3
"""Verify the public, semantic learning.operator source/document contract.

Private Rust function names are not contracts. Public API shape is compiled by
an independent consumer, behavior is exercised by Rust/mutation tests, and exact
identity is bound by generated implementation and readiness receipts.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATUS_PATH = "docs/modules/learning.operator/STATUS.json"
MAP_PATH = "docs/modules/learning.operator/IMPLEMENTATION_MAP.json"


def read(path: str) -> str:
    target = ROOT / path
    if not target.is_file():
        raise SystemExit(f"learning.operator contract verification failed: absent {path}")
    return target.read_text(encoding="utf-8")


def load_json(path: str) -> dict[str, Any]:
    try:
        value = json.loads(read(path))
    except json.JSONDecodeError as error:
        raise SystemExit(f"learning.operator contract verification failed: invalid JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise SystemExit(f"learning.operator contract verification failed: {path} must be an object")
    return value


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"learning.operator contract verification failed: {message}")


def require_tokens(path: str, tokens: tuple[str, ...] | list[str]) -> None:
    text = read(path)
    for token in tokens:
        require(token in text, f"{path} missing {token!r}")


def require_absent(path: str, tokens: tuple[str, ...] | list[str]) -> None:
    text = read(path)
    for token in tokens:
        require(token not in text, f"{path} retains forbidden {token!r}")


def verify_status() -> dict[str, Any]:
    status = load_json(STATUS_PATH)
    require(
        status.get("schema") == "hepta.learning-operator-status.v1"
        and status.get("schemaVersion") == 1
        and status.get("module") == "learning.operator",
        "canonical status schema/module",
    )
    require(status.get("canonicalStatusSource") is True, "STATUS.json must be canonical")
    require(status.get("defaultLoader") == "LoadedTabularOperatorV2", "default V2 loader")
    require(
        status.get("defaultLoop") == "coordinate_learning_operator_shadow_v1"
        and status.get("defaultLoopWired") is True,
        "default shadow loop status",
    )
    require(
        status.get("explicitReadConsumerComposed") is True
        and status.get("freshProcessLoadInAuthoritativeGate") is True
        and status.get("productShadowProtocolE2EInAuthoritativeGate") is True,
        "implemented protocol evidence status",
    )
    for key in (
        "productExecutionProved",
        "productionImplementation",
        "productionWriterEstablished",
        "independentScientificAcceptance",
        "targetHostCapacityAccepted",
        "operatorAcceptance",
        "canaryAccepted",
        "promotionAuthorized",
        "activation",
        "release",
    ):
        require(status.get(key) is False, f"{key} must remain false without external evidence")
    return status


def verify_default_surface() -> None:
    manifest = read("codex-rs/hepta-bellman-operator/Cargo.toml")
    require('path = "src/authoritative_lib.rs"' in manifest, "authoritative crate root")
    require(re.search(r"(?m)^default\s*=\s*\[\]$", manifest) is not None, "default features must remain empty")
    require('qualification-unverified-input = []' in manifest, "compatibility feature missing")
    surface = read("codex-rs/hepta-bellman-operator/src/authoritative_lib.rs")
    require("pub use legacy::*" not in surface, "wildcard legacy export is forbidden")
    for token in (
        'pub mod compatibility',
        'FinalUseTabularCapabilityV1',
        'FinalUseWorldModelCapabilityV1',
        'LoadedTabularOperatorV2',
        'QualifiedSensorCoreBuildReceiptV1',
        'SensorCoreSelectionModeV1',
        'build_sensor_core_qualified_v1',
    ):
        require(token in surface, f"authoritative public surface missing {token!r}")
    require_tokens(
        "scripts/hepta-learning-operator-api-surface.py",
        [
            "default-authoritative-pass",
            "feature-compatibility-pass",
            "raw-fitter",
            "compatibility-module",
            "activation-port",
            "publish-port",
        ],
    )


def verify_semantic_sensor_contract() -> None:
    require_tokens(
        "codex-rs/hepta-bellman-operator/src/sensor_core_qualification.rs",
        [
            "pub enum SensorCoreSelectionModeV1",
            'Self::Exact => "exact"',
            'Self::DeterministicallyReduced => "reduced"',
            "pub selection_mode: SensorCoreSelectionModeV1",
            "pub reduction_algorithm_digest: Digest32",
            "pub qualification_receipt_digest: Digest32",
            "build_sensor_core_qualified_v1",
            "semantic_receipt_reports_exact_and_reduced_modes",
            "bounded_geometry_degradation",
        ],
    )
    contract = read("scripts/hepta-learning-operator-contract.py")
    old_scan = 'require_tokens(\n        "codex-rs/hepta-bellman-operator/src/sensor_core_v2.rs"'
    require(old_scan not in contract, "private sensor implementation token scan remains")


def verify_final_use_contract() -> None:
    require_tokens(
        "codex-rs/hepta-bellman-operator/src/final_use_hardening.rs",
        [
            "issued_at_unix_micros",
            "absolute_deadline_unix_micros",
            "capability_issue_at_deadline_fails_closed",
            "use_at_deadline_fails_closed",
            "use_before_capability_issue_is_clock_regression",
            "publish_before_use_is_clock_regression",
        ],
    )
    require_tokens(
        "codex-rs/hepta-agentd/src/cognitive_ranker_admission.rs",
        [
            "pub struct RankerAdmissionSnapshotV2",
            "pub(crate) learning_verifier",
            "pub(crate) artifact_trust_digest",
            "pub(crate) runtime_profile_digest",
            "pub(crate) now_unix_micros",
            "LoadedTabularOperatorV2",
        ],
    )
    require_absent(
        "codex-rs/hepta-agentd/src/cognitive_ranker_admission.rs",
        [
            "pub learning_verifier:",
            "pub artifact_trust_digest:",
            "pub runtime_profile_digest:",
            "pub now_unix_micros:",
        ],
    )


def verify_status_projection(status: dict[str, Any]) -> None:
    implementation = load_json(MAP_PATH)
    require(implementation.get("module") == "learning.operator", "implementation map identity")
    boundary = implementation.get("claimBoundary")
    require(isinstance(boundary, dict), "implementation claim boundary")
    for status_key, map_key in {
        "explicitReadConsumerComposed": "explicitReadConsumerComposed",
        "defaultLoopWired": "defaultProductLoopWired",
        "productExecutionProved": "productExecutionProved",
        "productionImplementation": "productionImplementation",
        "activation": "activation",
        "release": "release",
    }.items():
        require(status.get(status_key) == boundary.get(map_key), f"status/map disagreement: {status_key}")
    require(
        implementation.get("productionWriterState") == "not_established"
        and status.get("productionWriterEstablished") is False,
        "production writer status",
    )
    operations = {
        row.get("operation")
        for row in implementation.get("operations", [])
        if isinstance(row, dict)
    }
    for operation in (
        "issue_tabular_final_use_capability_v1",
        "fit_tabular_final_use_v1",
        "issue_world_model_final_use_capability_v1",
        "fit_world_model_final_use_v1",
        "load_pinned_tabular_operator_v2",
        "coordinate_learning_operator_shadow_v1",
        "emit_qualification_manifest_v3",
    ):
        require(operation in operations, f"implementation operation absent: {operation}")


def verify_documents() -> None:
    documents = {
        "TECHNICAL.md": read("docs/modules/learning.operator/TECHNICAL.md"),
        "ADMISSION_CONTRACT.md": read("docs/modules/learning.operator/ADMISSION_CONTRACT.md"),
        "execution dossier": read("qualification/module-execution-dossiers/detail/learning.operator.md"),
    }
    for label, text in documents.items():
        lowered = text.lower()
        require("status.json" in lowered, f"{label} must name the canonical status source")
        require("activation remains false" in lowered, f"{label} must retain the activation boundary")
    for phrase in (
        "default training/evaluation/selection loop remains uncomposed",
        "default training/evaluation/selection composition",
    ):
        require(phrase not in documents["TECHNICAL.md"], f"TECHNICAL.md retains stale status: {phrase}")
        require(phrase not in documents["execution dossier"], f"execution dossier retains stale status: {phrase}")
    require("LoadedTabularOperatorV2" in documents["ADMISSION_CONTRACT.md"], "admission must name V2 loader")
    require("LoadedTabularOperatorV2" in documents["execution dossier"], "dossier must name V2 loader")


def verify_schema_and_wiring() -> None:
    compatibility = load_json("docs/modules/learning.operator/SCHEMA_COMPATIBILITY.json")
    require(
        compatibility.get("schema") == "hepta.learning-operator-schema-compatibility.v2"
        and compatibility.get("schemaVersion") == 2,
        "compatibility schema",
    )
    path = compatibility.get("defaultQualificationPath")
    require(isinstance(path, dict), "default qualification path")
    require(
        path.get("trainingProfile") == "TrainingProfileV1"
        and path.get("worldModelProfile") == "WorldModelProfileV1"
        and path.get("tabularCapability") == "FinalUseTabularCapabilityV1"
        and path.get("worldModelCapability") == "FinalUseWorldModelCapabilityV1"
        and path.get("hostLoop") == "coordinate_learning_operator_shadow_v1"
        and path.get("activationAllowed") is False,
        "default final-use qualification path",
    )
    workflow = read(".github/workflows/learning-operator-authoritative.yml")
    require("workflow_call:" in workflow and "contents: read" in workflow, "read-only reusable workflow")
    require("qualification-result" in workflow, "stable final qualification check")
    authoritative = read("scripts/hepta-learning-operator-authoritative.sh")
    for token in (
        "hepta-learning-operator-api-surface.py",
        "hepta-learning-operator-stage.py",
        "hepta-learning-operator-readiness.py",
        "fresh-process-load",
        "product-shadow-e2e",
        "synthetic-merge",
        "readiness-manifest.json",
    ):
        require(token in authoritative, f"authoritative qualification missing {token!r}")
    blocking = read(".github/workflows/blocking-ci.yml")
    require("uses: ./.github/workflows/learning-operator-authoritative.yml" in blocking, "protected CI fan-in")


def verify_source() -> None:
    status = verify_status()
    verify_default_surface()
    verify_semantic_sensor_contract()
    verify_final_use_contract()
    verify_status_projection(status)
    verify_documents()
    verify_schema_and_wiring()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["verify"])
    parser.add_argument("--receipt")
    args = parser.parse_args()
    verify_source()
    if args.receipt:
        subprocess.run(
            ["python3", "scripts/hepta-learning-operator-receipt.py", "verify", "--path", args.receipt],
            cwd=ROOT,
            check=True,
        )
        subprocess.run(
            [
                "python3",
                "scripts/hepta-learning-operator-readiness.py",
                "verify",
                "--path",
                str(Path(args.receipt).with_name("readiness-manifest.json")),
            ],
            cwd=ROOT,
            check=True,
        )
    print("learning.operator public semantic source/document contract verified")


if __name__ == "__main__":
    main()
