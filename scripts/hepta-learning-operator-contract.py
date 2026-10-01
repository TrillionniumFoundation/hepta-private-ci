#!/usr/bin/env python3
"""Verify the public, semantic learning.operator source/document contract.

Private Rust function names are not contracts. Public API shape is compiled by
an independent consumer, behavior is exercised by Rust/mutation tests, and exact
identity is bound by generated implementation and readiness receipts.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATUS_PATH = "docs/modules/learning.operator/STATUS.json"
MAP_PATH = "docs/modules/learning.operator/IMPLEMENTATION_MAP.json"
MAPPER = importlib.import_module("hepta-learning-operator-map")


def read(path: str) -> str:
    target = ROOT / path
    if not target.is_file():
        raise SystemExit(
            f"learning.operator contract verification failed: absent {path}"
        )
    return target.read_text(encoding="utf-8")


def load_json(path: str) -> dict[str, Any]:
    try:
        value = json.loads(read(path))
    except json.JSONDecodeError as error:
        raise SystemExit(
            f"learning.operator contract verification failed: invalid JSON {path}: {error}"
        ) from error
    if not isinstance(value, dict):
        raise SystemExit(
            f"learning.operator contract verification failed: {path} must be an object"
        )
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


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def exact_sha(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) is not None


def verify_status() -> dict[str, Any]:
    status = load_json(STATUS_PATH)
    schema = load_json("docs/modules/learning.operator/STATUS.schema.json")
    properties = schema.get("properties")
    required = schema.get("required")
    require(
        schema.get("type") == "object"
        and schema.get("additionalProperties") is False
        and isinstance(properties, dict)
        and isinstance(required, list)
        and set(required) == set(properties)
        and set(status) == set(required),
        "canonical status must match its closed schema",
    )
    # STATUS.schema.json deliberately uses a flat const/boolean/string subset;
    # reject unsupported definitions instead of silently skipping constraints.
    for key, rule in properties.items():
        require(isinstance(rule, dict), f"malformed canonical status schema: {key}")
        if set(rule) == {"const"}:
            require(
                type(status[key]) is type(rule["const"])
                and status[key] == rule["const"],
                f"canonical status constant mismatch: {key}",
            )
        elif rule == {"type": "boolean"}:
            require(
                type(status[key]) is bool, f"canonical status boolean required: {key}"
            )
        elif rule == {"type": "string", "minLength": 1}:
            require(
                isinstance(status[key], str) and bool(status[key]),
                f"canonical status nonempty string required: {key}",
            )
        else:
            require(False, f"unsupported canonical status schema constraint: {key}")
    require(
        status.get("schema") == "hepta.learning-operator-status.v1"
        and status.get("schemaVersion") == 1
        and status.get("module") == "learning.operator",
        "canonical status schema/module",
    )
    require(
        status.get("canonicalStatusSource") is True, "STATUS.json must be canonical"
    )
    require(
        status.get("defaultLoader") == "LoadedTabularOperatorV2", "default V2 loader"
    )
    require(
        status.get("defaultLoop") == "coordinate_learning_operator_shadow_v1"
        and status.get("shadowCoordinatorImplemented") is True
        and status.get("defaultLoopWired") is False
        and status.get("canonicalWireAdaptersImplemented") is False,
        "shadow coordinator and partial real adapters implemented; complete default runtime and native wire admission remain uncomposed",
    )
    require(
        status.get("explicitReadConsumerComposed") is True
        and status.get("freshProcessLoadInAuthoritativeGate") is True
        and status.get("productShadowProtocolE2EInAuthoritativeGate") is True,
        "implemented protocol evidence status",
    )
    for key in (
        "registeredTransportCodecsImplemented",
        "sealedQualificationConsumersImplemented",
        "durableArtifactPersistenceAdapterImplemented",
        "evaluatedReadonlyShadowLoaderImplemented",
        "processRootTrustAndHostClockImplemented",
    ):
        require(status.get(key) is True, f"implemented component status: {key}")
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
        require(
            status.get(key) is False,
            f"{key} must remain false without external evidence",
        )
    return status


def verify_default_surface() -> None:
    manifest = read("codex-rs/hepta-bellman-operator/Cargo.toml")
    require('path = "src/authoritative_lib.rs"' in manifest, "authoritative crate root")
    bazel = read("codex-rs/hepta-bellman-operator/BUILD.bazel")
    require(
        re.search(
            r'(?m)^\s*crate_root\s*=\s*"src/authoritative_lib\.rs"\s*,?\s*$', bazel
        )
        is not None,
        "Cargo/Bazel authoritative crate-root parity",
    )
    macro = read("defs.bzl")
    declaration = re.search(
        r"(?ms)^def codex_rust_crate\((?P<args>.*?)\):(?P<body>.*?)(?=^def |\Z)",
        macro,
    )
    require(
        declaration is not None
        and re.search(r"\bcrate_root\s*=\s*None\b", declaration["args"]) is not None
        and re.search(
            r"\blib_rule\s*\([^)]*\bcrate_root\s*=\s*crate_root\s*,",
            declaration["body"],
            re.DOTALL,
        )
        is not None,
        "Bazel macro must forward the selected crate root to rust_library",
    )
    require(
        re.search(r"(?m)^default\s*=\s*\[\]$", manifest) is not None,
        "default features must remain empty",
    )
    require(
        "qualification-unverified-input = []" in manifest,
        "compatibility feature missing",
    )
    surface_path = "codex-rs/hepta-bellman-operator/src/authoritative_lib.rs"
    surface = read(surface_path)
    require("pub use legacy::*" not in surface, "wildcard legacy export is forbidden")
    for token in (
        "pub mod compatibility",
        "FinalUseTabularCapabilityV1",
        "FinalUseWorldModelCapabilityV1",
        "LoadedTabularOperatorV2",
        "QualifiedSensorCoreBuildReceiptV1",
        "SensorCoreSelectionModeV1",
        "build_sensor_core_qualified_v1",
    ):
        require(token in surface, f"authoritative public surface missing {token!r}")
    for forbidden in (
        "pub use legacy::VerifiedTabularOperatorPlanV3;",
        "pub use legacy::VerifiedWorldModelDatasetV3;",
        "pub use legacy::fit_tabular_operator_verified_v3;",
        "pub use legacy::fit_transition_model_verified_v3;",
        "pub use legacy::verify_tabular_operator_plan_v3;",
        "pub use legacy::verify_world_model_dataset_v3;",
    ):
        require(
            forbidden not in surface,
            f"default surface exposes direct V3 bypass: {forbidden}",
        )
    require_tokens(
        "scripts/hepta-learning-operator-api-surface.py",
        [
            "default-authoritative-pass",
            "feature-compatibility-pass",
            "raw-fitter",
            "bounded-raw-fitter",
            "direct-v3-tabular-verifier",
            "direct-v3-tabular-fitter",
            "direct-v3-world-verifier",
            "direct-v3-world-fitter",
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
            "pub full_input_candidate_digest: Digest32",
            "pub full_input_fill_distance_q32: FixedQ32",
            "pub full_input_mesh_ratio_q32: FixedQ32",
            "pub total_work: OperatorWorkSnapshotV1",
            "clustered_outlier_cannot_hide_behind_working_set_geometry",
            "full_input_geometry_work_is_budgeted",
        ],
    )
    contract = read("scripts/hepta-learning-operator-contract.py")
    old_scan = (
        "require_tokens(\n"
        '        "codex-rs/hepta-bellman-operator/src/sensor_core_v2.rs"'
    )
    require(
        old_scan not in contract, "private sensor implementation token scan remains"
    )


def verify_fit_context_contract() -> None:
    require_tokens(
        "codex-rs/hepta-bellman-operator/src/budget.rs",
        [
            "struct FitBudgetLedger",
            "operations: AtomicU64",
            "reserved_bytes: AtomicU64",
            "BudgetExpansion",
            "operation_budget_is_cumulative_across_worker_meters",
            "concurrent_memory_reservations_share_one_absolute_ceiling",
            "worker_cannot_expand_an_already_bound_budget",
        ],
    )


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
            "pub(crate) learning_trust: ActivatedLearningTrustV1",
            "learning_trust.distribution_digest()",
            ".revalidate_at(snapshot.now_unix_micros)",
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
            "pub learning_trust:",
            "pub artifact_trust_digest:",
            "pub runtime_profile_digest:",
            "pub now_unix_micros:",
        ],
    )


def verify_status_projection(status: dict[str, Any]) -> None:
    implementation = load_json(MAP_PATH)
    require(
        implementation.get("module") == "learning.operator",
        "implementation map identity",
    )
    require(
        implementation.get("statusSource") == STATUS_PATH,
        "implementation map must point to canonical STATUS.json",
    )
    require(
        implementation.get("statusProjectionSha256") == sha256_text(read(STATUS_PATH)),
        "implementation map status projection digest drift",
    )
    require(
        implementation.get("sourceIdentityRole") == "navigation_provenance_only",
        "checked-in map identity must be navigation-only",
    )
    require(
        implementation.get("qualificationIdentitySource")
        == status.get("sourceIdentityPolicy"),
        "qualification identity must be derived from STATUS.json",
    )
    require(
        implementation.get("sourceIdentityPolicy")
        == "candidate_or_exact_observation_v1",
        "navigation map must use the repository-supported observation policy",
    )
    source_base = implementation.get("sourceBase")
    observed = implementation.get("observedAtHead")
    require(
        isinstance(source_base, dict)
        and isinstance(observed, dict)
        and exact_sha(source_base.get("commit"))
        and exact_sha(source_base.get("tree"))
        and source_base == observed,
        "navigation source observation must be exact and self-consistent",
    )

    boundary = implementation.get("claimBoundary")
    require(isinstance(boundary, dict), "implementation claim boundary")
    for status_key, map_key in {
        "explicitReadConsumerComposed": "explicitReadConsumerComposed",
        "shadowCoordinatorImplemented": "shadowCoordinatorImplemented",
        "canonicalWireAdaptersImplemented": "canonicalWireAdaptersImplemented",
        "registeredTransportCodecsImplemented": "registeredTransportCodecsImplemented",
        "sealedQualificationConsumersImplemented": "sealedQualificationConsumersImplemented",
        "durableArtifactPersistenceAdapterImplemented": "durableArtifactPersistenceAdapterImplemented",
        "evaluatedReadonlyShadowLoaderImplemented": "evaluatedReadonlyShadowLoaderImplemented",
        "processRootTrustAndHostClockImplemented": "processRootTrustAndHostClockImplemented",
        "defaultLoopWired": "defaultProductLoopWired",
        "freshProcessLoadInAuthoritativeGate": "freshProcessLoadInAuthoritativeGate",
        "productShadowProtocolE2EInAuthoritativeGate": "productShadowProtocolE2EInAuthoritativeGate",
        "productExecutionProved": "productExecutionProved",
        "productionImplementation": "productionImplementation",
        "activation": "activation",
        "release": "release",
    }.items():
        require(
            type(status.get(status_key)) is type(boundary.get(map_key))
            and status.get(status_key) == boundary.get(map_key),
            f"status/map disagreement: {status_key}",
        )
    require(
        type(implementation.get("productionImplementation"))
        is type(status.get("productionImplementation"))
        and implementation.get("productionImplementation")
        == status.get("productionImplementation"),
        "top-level production implementation status",
    )
    require(
        implementation.get("productCallerState")
        == "explicit_read_and_sealed_qualification_consumers_real_persistence_api_and_shadow_loader_implemented_full_default_loop_uncomposed"
        and status.get("explicitReadConsumerComposed") is True
        and status.get("shadowCoordinatorImplemented") is True
        and status.get("defaultLoopWired") is False,
        "product caller projection",
    )
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
        "emit_qualification_readiness_v1",
        "assert_default_public_api_v1",
    ):
        require(
            operation in operations, f"implementation operation absent: {operation}"
        )


def verify_documents() -> None:
    documents = {
        "TECHNICAL.md": read("docs/modules/learning.operator/TECHNICAL.md"),
        "ADMISSION_CONTRACT.md": read(
            "docs/modules/learning.operator/ADMISSION_CONTRACT.md"
        ),
        "execution dossier": read(
            "qualification/module-execution-dossiers/detail/learning.operator.md"
        ),
    }
    for label, text in documents.items():
        lowered = text.lower()
        normalized = " ".join(lowered.split())
        require(
            "status.json" in lowered,
            f"{label} must name the canonical status source",
        )
        require(
            "activation remains false" in normalized
            or "activation and release remain false" in normalized,
            f"{label} must retain the activation boundary",
        )
    require(
        "LoadedTabularOperatorV2" in documents["ADMISSION_CONTRACT.md"],
        "admission must name V2 loader",
    )
    require(
        "LoadedTabularOperatorV2" in documents["execution dossier"],
        "dossier must name V2 loader",
    )


def verify_qualification_tools(workflow: str) -> None:
    installed = {
        tool.strip()
        for declaration in re.findall(r"^\s+tool:\s*([^\n]+)$", workflow, re.MULTILINE)
        for tool in declaration.split(",")
    }
    for tool in ("cargo-llvm-cov@0.9.1", "just@1.51.0", "nextest@0.9.103"):
        require(
            tool in installed,
            f"authoritative qualification runner missing pinned {tool}",
        )


def verify_product_ci_scope(workflow: str) -> None:
    for root in (*MAPPER.PRODUCT_DEPENDENCY_ROOTS, *MAPPER.EXECUTION_CONTROL_ROOTS):
        require(
            f"- '{root}/**'" in workflow,
            f"operator audit trigger omits product dependency {root}",
        )
    for path in (
        "codex-rs/Cargo.toml",
        "codex-rs/Cargo.lock",
        "codex-rs/rust-toolchain.toml",
        "justfile",
        "BUILD.bazel",
        ".gitattributes",
        "docs/contracts/CONTRACTS.json",
        "docs/contracts/PROTOCOL_SCHEMAS.json",
        ".github/workflows/learning-operator-authoritative.yml",
        *MAPPER.EXECUTION_CONTROL_PATHS,
    ):
        require(
            f"- '{path}'" in workflow,
            f"operator audit trigger omits execution control {path}",
        )


def verify_v8_provisioning(workflow: str) -> None:
    provisioning = [
        step
        for step in re.finditer(
            r"(?ms)^      - name: [^\n]+\n.*?(?=^      - (?:name:|uses:)|\Z)",
            workflow,
        )
        if re.search(
            r"(?m)^        run: python3 scripts/hepta_ci_v8\.py$", step.group()
        )
    ]
    require(len(provisioning) == 1, "one actual V8 provisioner step is required")
    setup = provisioning[0]
    require(
        "CODEX_REPO_ROOT: ${{ github.workspace }}" in setup.group()
        and "PYTHONPATH: scripts" in setup.group()
        and re.search(r"(?m)^        if:", setup.group()) is None,
        "V8 provisioning must unconditionally bind the source workspace and resolver",
    )
    execution = workflow.find("bash scripts/hepta-learning-operator-authoritative.sh")
    require(
        execution >= 0 and setup.start() < execution,
        "V8 provisioning must precede native qualification execution",
    )


def verify_schema_and_wiring() -> None:
    compatibility = load_json(
        "docs/modules/learning.operator/SCHEMA_COMPATIBILITY.json"
    )
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
    require(
        "workflow_call:" in workflow and "contents: read" in workflow,
        "read-only reusable workflow",
    )
    require("qualification-result" in workflow, "stable final qualification check")
    verify_qualification_tools(workflow)
    verify_v8_provisioning(workflow)
    verify_product_ci_scope(read(".github/workflows/hepta-learning-operator-audit.yml"))
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
        require(
            token in authoritative,
            f"authoritative qualification missing {token!r}",
        )
    blocking = read(".github/workflows/blocking-ci.yml")
    require(
        "uses: ./.github/workflows/learning-operator-authoritative.yml" in blocking,
        "protected CI fan-in",
    )


def verify_source() -> None:
    status = verify_status()
    verify_default_surface()
    verify_semantic_sensor_contract()
    verify_fit_context_contract()
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
            [
                "python3",
                "scripts/hepta-learning-operator-receipt.py",
                "verify",
                "--path",
                args.receipt,
            ],
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
