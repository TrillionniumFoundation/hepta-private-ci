#!/usr/bin/env python3
"""Read-only closed-world verifier for the Lane E implementation candidate."""

from __future__ import annotations

import argparse
import json
import re
import sys
import stat
import subprocess
import tomllib
from hepta_rust_surface import without_disabled_feature_items
from dataclasses import dataclass
from pathlib import Path

from hepta_workflow_commands import workflow_commands
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = ROOT / "docs/lane-e/LANE_E_IMPLEMENTATION_MATRIX.json"
TRACE_PATH = ROOT / "qualification/lane-e/TEST_TRACEABILITY.json"
WORKFLOW_PATH = ROOT / ".github/workflows/hepta-lane-e-gap-closure.yml"
PRODUCTION_CONTRACT_PATH = (
    ROOT / "codex-rs/hepta-intelligence-eval/PRODUCTION_CONTRACT.md"
)
EVIDENCE_SCRIPT_PATH = ROOT / "scripts/hepta-learning-eval-evidence.py"
TEMPORARY_WORKFLOW_PATH = (
    ROOT / ".github/workflows/hepta-lane-e-materialize-generated.yml"
)

EXPECTED_MODULES = {
    "learning.ledger",
    "learning.operator",
    "learning.eval",
    "learning.artifacts",
}
EXPECTED_CASES = {
    *(f"LEDGER-{index:02d}" for index in range(1, 14)),
    *(f"OP-{index:02d}" for index in range(1, 7)),
    *(f"EVAL-{index:02d}" for index in range(1, 8)),
    *(f"ART-{index:02d}" for index in range(1, 13)),
}
EXPECTED_EXTERNAL_GATES = {f"RDY-EXT-{index:03d}" for index in range(1, 10)}
EXPECTED_OPERATIONS = {
    "learning.ledger": {
        "LedgerWriter::rotate_trust",
        "measure_ledger_recovery_work",
        "LedgerWriter::append_decision",
        "LedgerWriter::append_outcome",
        "LedgerWriter::append_credit_batch",
        "LedgerWriter::append_unlearning",
        "LedgerWriter::freeze_dataset",
        "LedgerWriter::revalidate_dataset_snapshot",
        "LedgerWriter::rotate_segment",
        "sync_directory_handle",
        "LedgerWitnessStore",
        "activate_learning_trust",
        "canonical_protocol_adapters",
        "build_ledger_index_checkpoint",
        "validate_candidate_set_completeness",
    },
    "learning.artifacts": {
        "validate_artifact_manifest_v2",
        "DatasetWithdrawalRegistry::append",
        "validate_registry_head_witness",
        "admit_manifest_at_withdrawal_head_v3",
        "ArtifactPublicationTransactionV1::begin",
        "ArtifactPublicationTransactionV1::record_registry_durable",
        "ArtifactPublicationTransactionV1::record_witness_durable",
        "ArtifactPublicationTransactionV1::acknowledge",
        "ArtifactLifecycleJournalV2::append",
        "write_dataset_withdrawal_snapshot",
        "write_artifact_lifecycle_snapshot",
        "project_operator_sensor_core_registry_v1",
        "IterationLedgerV1::transition",
        "LearningArtifactOwnerHost::open",
        "LearningArtifactOwnerHost::open_with_required_current_head",
        "LearningArtifactOwnerHost::recover_registry_by_head",
        "LearningArtifactOwnerHost::recover_current_registry",
        "LearningArtifactOwnerHost::current_registry_view",
        "ArtifactOwnerVerifierV1::verify_current_registry_view",
        "LearningArtifactOwnerHost::recovery_required_operations",
        "LearningArtifactOwnerService::open",
        "LearningArtifactOwnerService::current_registry_view",
        "LearningArtifactOwnerService::publish",
        "load_pinned_candidate",
        "ArtifactSelectionVerifierV1::verify",
        "record_verified_selection",
        "load_selected_candidate",
    },
    "learning.operator": {
        "build_targets",
        "build_sensor_core",
        "evaluate_bellman_reference",
        "validate_applicability_certificate",
        "validate_applicability_with_signed_evidence_v2",
        "fit_tabular_operator",
        "fit_tabular_operator_strict_v2",
        "verify_tabular_operator_plan_v2",
        "fit_tabular_operator_verified_v2",
        "predict_tabular_operator",
        "encode_tabular_payload_v1",
        "load_pinned_tabular_operator_v1",
        "admit_operator_regularity",
        "admit_operator_regularity_with_signed_evidence_v2",
        "fit_transition_model",
        "verify_world_model_dataset_v2",
        "fit_transition_model_verified_v2",
        "predict_transition",
        "freeze_terminal_cell_from_owner_v1",
        "fit_terminal_cell_from_owner_v1",
    },
    "learning.eval": {
        "estimate_ope",
        "estimate_cluster_intervals",
        "estimate_sequential",
        "freeze_product_evaluation_plan_v1",
        "ProductEvaluationRunnerV1::evaluate_temporal_comparison",
        "ProductEvaluationRunnerV1::qualify_and_persist",
        "FencedFinalHoldoutOwnerV1::consume",
        "LockedFileFinalHoldoutCasStoreV1",
        "decide_with_signed_evidence_v2",
        "decide_with_signed_longitudinal_evidence_v3",
    },
}
EXPECTED_CRATES = {
    "codex-hepta-learning-ledger",
    "codex-hepta-learning-artifacts",
    "codex-hepta-bellman-operator",
    "codex-hepta-intelligence-eval",
    "codex-hepta-intelligence",
    "codex-hepta-shadow-qualification",
}


@dataclass(frozen=True)
class Finding:
    code: str
    message: str


class Findings:
    def __init__(self) -> None:
        self.items: list[Finding] = []

    def add(self, code: str, message: str) -> None:
        self.items.append(Finding(code=code, message=message))

    def require(self, condition: bool, code: str, message: str) -> None:
        if not condition:
            self.add(code, message)


def load_json(path: Path, findings: Findings) -> dict[str, Any]:
    if not path.is_file():
        findings.add(
            "missing_file", f"missing required JSON file: {path.relative_to(ROOT)}"
        )
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        findings.add(
            "invalid_json",
            f"cannot parse {path.relative_to(ROOT)}: {error}",
        )
        return {}
    if not isinstance(value, dict):
        findings.add("invalid_json_root", f"{path.relative_to(ROOT)} must be an object")
        return {}
    return value


def relative_path(value: object, findings: Findings, context: str) -> Path | None:
    if not isinstance(value, str) or not value or value.startswith(("/", "../")):
        findings.add(
            "invalid_path", f"{context} has invalid repository path: {value!r}"
        )
        return None
    path = Path(value)
    if ".." in path.parts:
        findings.add("invalid_path", f"{context} escapes the repository: {value!r}")
        return None
    return ROOT / path


def verify_symbol(source: str, native_symbol: str) -> bool:
    parts = native_symbol.split("::")
    function = parts[-1]
    if function[:1].isupper():
        return bool(
            re.search(
                rf"\b(?:struct|enum|type|trait)\s+{re.escape(function)}\b", source
            )
        )
    if not re.search(
        rf"\b(?:pub(?:\([^)]*\))?\s+)?fn\s+{re.escape(function)}"
        rf"(?:\s*<[^{{}};]*>)?\s*\(",
        source,
    ):
        return False
    if len(parts) >= 2 and parts[-2][:1].isupper():
        owner = parts[-2]
        return bool(
            re.search(rf"\b(?:struct|enum|type)\s+{re.escape(owner)}\b", source)
            and re.search(rf"\bimpl(?:\s*<[^{{}};]*>)?\s+{re.escape(owner)}\b", source)
        )
    return True


def verify_matrix(
    matrix: dict[str, Any], findings: Findings
) -> dict[str, dict[str, Any]]:
    findings.require(
        matrix.get("schema") == "hepta.lane-e-implementation-matrix.v1",
        "matrix_schema",
        "unexpected Lane E matrix schema",
    )
    findings.require(
        matrix.get("authorityDelta") == "none",
        "authority_delta",
        "Lane E candidate must not grant new authority",
    )
    findings.require(
        matrix.get("capabilityClosureState") == "external_evidence_required",
        "capability_truth_boundary",
        "capability closure must remain external-evidence-required",
    )

    modules_raw = matrix.get("modules")
    if not isinstance(modules_raw, list):
        findings.add("matrix_modules", "matrix modules must be an array")
        return {}
    modules: dict[str, dict[str, Any]] = {}
    for item in modules_raw:
        if not isinstance(item, dict) or not isinstance(item.get("module"), str):
            findings.add(
                "matrix_module_record", "matrix contains an invalid module record"
            )
            continue
        module = item["module"]
        if module in modules:
            findings.add("duplicate_module", f"duplicate module in matrix: {module}")
            continue
        modules[module] = item

    findings.require(
        set(modules) == EXPECTED_MODULES,
        "module_closed_world",
        f"matrix modules must be exactly {sorted(EXPECTED_MODULES)}",
    )
    for module, item in modules.items():
        required_paths = ["sourceRoot", "stableGuide", "dossier", "nativeMapping"]
        if module == "learning.eval":
            required_paths.append("productionContract")
        for key in required_paths:
            path = relative_path(item.get(key), findings, f"{module}.{key}")
            if path is not None:
                findings.require(
                    path.exists(),
                    "missing_matrix_path",
                    f"{module}.{key} does not exist: {path.relative_to(ROOT)}",
                )
        findings.require(
            item.get("remainingRepositoryGaps") == [],
            "repository_gap_open",
            f"{module} still lists a repository-controlled gap",
        )
        external = item.get("remainingExternalEvidence")
        findings.require(
            isinstance(external, list) and bool(external),
            "external_evidence_missing",
            f"{module} must truthfully retain applicable external evidence",
        )

        operations_raw = item.get("operations")
        if not isinstance(operations_raw, list):
            findings.add("operations_missing", f"{module} has no operations array")
            continue
        operations: dict[str, dict[str, Any]] = {}
        for operation in operations_raw:
            if not isinstance(operation, dict) or not isinstance(
                operation.get("operation"), str
            ):
                findings.add("invalid_operation", f"{module} has an invalid operation")
                continue
            operations[operation["operation"]] = operation
        findings.require(
            set(operations) == EXPECTED_OPERATIONS[module],
            "operation_closed_world",
            f"{module} operation set differs from the required closed world",
        )
        for operation_name, operation in operations.items():
            source_path = relative_path(
                operation.get("source"), findings, f"{module}.{operation_name}.source"
            )
            symbol = operation.get("nativeSymbol")
            if source_path is None or not source_path.is_file():
                findings.add(
                    "operation_source_missing",
                    f"missing source for {module}.{operation_name}",
                )
                continue
            if not isinstance(symbol, str):
                findings.add(
                    "native_symbol_missing",
                    f"missing native symbol for {module}.{operation_name}",
                )
                continue
            source = source_path.read_text(encoding="utf-8")
            findings.require(
                verify_symbol(source, symbol),
                "native_symbol_unresolved",
                f"cannot resolve {symbol} in {source_path.relative_to(ROOT)}",
            )
            status = operation.get("status")
            findings.require(
                operation.get("status")
                in {
                    "implemented_pairwise_independence",
                    "implemented_rebuildable",
                    "implemented",
                    "implemented_sealed_receipt",
                    "implemented_current_state_revalidation",
                    "implemented_existing",
                    "implemented_verified_source_dataset_membership_artifact_handoff",
                    "implemented_directory_sync_before_witness",
                    "implemented_ledger_derived",
                    "implemented_root_authenticated_distribution_transport_external",
                    "implemented_host_authorized_directory_fsync",
                    "implemented_atomic_conservation",
                    "implemented_low_level",
                    "implemented_compatibility",
                },
                "operation_not_implemented",
                f"{module}.{operation_name} is not source-implemented",
            )

    external_raw = matrix.get("externalGates")
    external: dict[str, dict[str, Any]] = {}
    if isinstance(external_raw, list):
        for item in external_raw:
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                external[item["id"]] = item
    findings.require(
        set(external) == EXPECTED_EXTERNAL_GATES,
        "external_gate_closed_world",
        "external gate set must contain RDY-EXT-001 through RDY-EXT-009 exactly",
    )
    for gate_id, item in external.items():
        findings.require(
            item.get("repositoryMaySelfCertify") is False,
            "external_gate_self_certified",
            f"{gate_id} may not be self-certified by repository source",
        )
        state = item.get("state")
        findings.require(
            isinstance(state, str)
            and ("open" in state or "required" in state)
            and "closed" not in state,
            "external_gate_false_closure",
            f"{gate_id} must remain open or evidence-required: {state!r}",
        )

    cross = matrix.get("crossCrateQualification")
    if not isinstance(cross, dict):
        findings.add(
            "cross_crate_missing", "cross-crate qualification record is missing"
        )
    else:
        path = relative_path(
            cross.get("source"), findings, "crossCrateQualification.source"
        )
        test = cross.get("test")
        if path is not None and path.is_file() and isinstance(test, str):
            text = path.read_text(encoding="utf-8")
            findings.require(
                bool(re.search(rf"\bfn\s+{re.escape(test)}\s*\(", text)),
                "cross_crate_test_missing",
                f"cross-crate test function is missing: {test}",
            )
        else:
            findings.add("cross_crate_source", "cross-crate test source is missing")
    return modules


def verify_traceability(
    trace: dict[str, Any], modules: dict[str, dict[str, Any]], findings: Findings
) -> None:
    findings.require(
        trace.get("schema") == "hepta.lane-e-test-traceability.v1",
        "trace_schema",
        "unexpected Lane E traceability schema",
    )
    cases_raw = trace.get("cases")
    if not isinstance(cases_raw, list):
        findings.add("trace_cases", "traceability cases must be an array")
        return
    cases: dict[str, dict[str, Any]] = {}
    for item in cases_raw:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            findings.add("invalid_case", "traceability contains an invalid case")
            continue
        case_id = item["id"]
        if case_id in cases:
            findings.add("duplicate_case", f"duplicate case: {case_id}")
            continue
        cases[case_id] = item
    findings.require(
        set(cases) == EXPECTED_CASES,
        "case_closed_world",
        f"traceability cases must be exactly {sorted(EXPECTED_CASES)}",
    )

    source_cache: dict[Path, str] = {}
    dossier_cache: dict[Path, str] = {}
    for case_id, case in cases.items():
        module = case.get("module")
        findings.require(
            module in EXPECTED_MODULES,
            "case_module",
            f"{case_id} has invalid module {module!r}",
        )
        if module in modules:
            dossier = relative_path(
                modules[module].get("dossier"), findings, f"{case_id}.dossier"
            )
            if dossier is not None and dossier.is_file():
                dossier_text = dossier_cache.setdefault(
                    dossier, dossier.read_text(encoding="utf-8")
                )
                findings.require(
                    case_id in dossier_text,
                    "dossier_case_missing",
                    f"{case_id} is absent from {dossier.relative_to(ROOT)}",
                )
        tests = case.get("tests")
        if not isinstance(tests, list) or not tests:
            findings.add("case_tests_missing", f"{case_id} has no mapped native tests")
            continue
        for index, test in enumerate(tests):
            context = f"{case_id}.tests[{index}]"
            if not isinstance(test, dict):
                findings.add("invalid_test_mapping", f"{context} is not an object")
                continue
            source_path = relative_path(
                test.get("source"), findings, f"{context}.source"
            )
            function = test.get("function")
            if source_path is None or not source_path.is_file():
                findings.add("test_source_missing", f"{context} source is missing")
                continue
            if not isinstance(function, str):
                findings.add("test_function_missing", f"{context} function is missing")
                continue
            source_text = source_cache.setdefault(
                source_path, source_path.read_text(encoding="utf-8")
            )
            findings.require(
                bool(re.search(rf"\bfn\s+{re.escape(function)}\s*\(", source_text)),
                "test_function_unresolved",
                f"{function} is absent from {source_path.relative_to(ROOT)}",
            )
        findings.require(
            case.get("status") == "native_test_mapped",
            "case_status",
            f"{case_id} is not marked native_test_mapped",
        )

    cross_raw = trace.get("crossCrateCases")
    findings.require(
        isinstance(cross_raw, list) and len(cross_raw) == 1,
        "cross_case_count",
        "exactly one Lane E cross-crate case is required",
    )
    if isinstance(cross_raw, list):
        for item in cross_raw:
            if not isinstance(item, dict):
                findings.add("invalid_cross_case", "invalid cross-crate case")
                continue
            source_path = relative_path(
                item.get("source"), findings, "crossCase.source"
            )
            function = item.get("function")
            if (
                source_path is not None
                and source_path.is_file()
                and isinstance(function, str)
            ):
                text = source_path.read_text(encoding="utf-8")
                findings.require(
                    bool(re.search(rf"\bfn\s+{re.escape(function)}\s*\(", text)),
                    "cross_case_unresolved",
                    f"cross-crate function is missing: {function}",
                )

    # Product-boundary tests are tracked separately from the Lane E causal
    # chain: they exercise a real non-Rust consumer and an injected fault.
    # Keeping this as an explicit trace prevents a passing unit test from being
    # mistaken for cross-language product evidence.
    boundary_raw = trace.get("productBoundaryCases")
    findings.require(
        isinstance(boundary_raw, list) and len(boundary_raw) == 1,
        "product_boundary_case_count",
        "exactly one product-boundary case is required",
    )
    if isinstance(boundary_raw, list):
        for item in boundary_raw:
            if not isinstance(item, dict):
                findings.add("invalid_boundary_case", "invalid product-boundary case")
                continue
            source_path = relative_path(
                item.get("source"), findings, "productBoundaryCase.source"
            )
            function = item.get("function")
            if source_path is None or not source_path.is_file():
                findings.add(
                    "boundary_source_missing", "product-boundary source is missing"
                )
                continue
            findings.require(
                isinstance(function, str),
                "boundary_function_missing",
                "product-boundary function is missing",
            )
            if isinstance(function, str):
                text = source_path.read_text(encoding="utf-8")
                findings.require(
                    bool(re.search(rf"\bfn\s+{re.escape(function)}\s*\(", text)),
                    "boundary_function_unresolved",
                    f"product-boundary function is missing: {function}",
                )


def verify_learning_eval_production_boundary(findings: Findings) -> None:
    lib_path = ROOT / "codex-rs/hepta-intelligence-eval/src/lib.rs"
    closure_path = ROOT / "codex-rs/hepta-intelligence-eval/src/closure.rs"
    metric_path = ROOT / "codex-rs/hepta-intelligence-eval/src/metric_roles.rs"
    durable_path = ROOT / "codex-rs/hepta-intelligence-eval/src/fenced_holdout.rs"
    cargo_path = ROOT / "codex-rs/hepta-intelligence-eval/Cargo.toml"
    api_contract_path = (
        ROOT / "codex-rs/hepta-shadow-qualification/tests/lane_e_api_contract.rs"
    )
    required = [
        lib_path,
        closure_path,
        metric_path,
        durable_path,
        cargo_path,
        api_contract_path,
        PRODUCTION_CONTRACT_PATH,
        EVIDENCE_SCRIPT_PATH,
    ]
    for path in required:
        findings.require(
            path.is_file(),
            "learning_eval_boundary_file_missing",
            f"missing learning.eval production boundary file: {path.relative_to(ROOT)}",
        )
    if not all(path.is_file() for path in required):
        return

    lib = lib_path.read_text(encoding="utf-8")
    closure = closure_path.read_text(encoding="utf-8")
    metric = metric_path.read_text(encoding="utf-8")
    durable = durable_path.read_text(encoding="utf-8")
    cargo = cargo_path.read_text(encoding="utf-8")
    api_contract = api_contract_path.read_text(encoding="utf-8")
    production = PRODUCTION_CONTRACT_PATH.read_text(encoding="utf-8")
    evidence_script = EVIDENCE_SCRIPT_PATH.read_text(encoding="utf-8")

    findings.require(
        "pub fn evaluate(mut request: EvaluationRequest)" not in lib,
        "learning_eval_legacy_public",
        "legacy evaluate() must not be part of the default public surface",
    )
    findings.require(
        "pub fn decide_independently(" not in closure,
        "learning_eval_unsigned_public",
        "unsigned decide_independently() must remain crate-private",
    )
    findings.require(
        "pub fn decide_independently_v2(" not in metric,
        "learning_eval_unsigned_v2_public",
        "unsigned decide_independently_v2() must remain crate-private",
    )
    for token in (
        "trusted-inprocess-eval = []",
        "pub mod trusted_inprocess",
        "pub(crate) use signed_evaluation::decide_with_signed_evidence_v2;",
        "pub(crate) use longitudinal_time::decide_with_signed_longitudinal_evidence_v3;",
    ):
        findings.require(
            token in (cargo + "\n" + lib),
            "learning_eval_signed_surface",
            f"missing required production/compatibility surface token: {token}",
        )
    for token in (
        "pub trait FinalHoldoutCasStoreV1",
        "pub struct FencedFinalHoldoutOwnerV1",
        "pub fn consume(",
    ):
        findings.require(
            token in durable,
            "learning_eval_holdout_fencing",
            f"missing durable holdout boundary: {token}",
        )
    for token in (
        "ProductEvaluationRunnerV1",
        "FencedFinalHoldoutOwnerV1",
        "DENY_ALL",
    ):
        findings.require(
            token in production,
            "learning_eval_production_contract",
            f"production contract is missing normative token: {token}",
        )
    for token in (
        "sourceTree",
        "candidate SHA/tree binding mismatch",
        "synthetic-merge first parent mismatch",
        "qualificationOutputs",
        "lineCoverageThresholdPct",
        "stressIterations",
        "stressLog",
    ):
        findings.require(
            token in evidence_script,
            "learning_eval_evidence_binding",
            f"evidence verifier is missing provenance/output binding: {token}",
        )
    for token in (
        "ProductEvaluationRunnerV1",
        "freeze_product_evaluation_plan_v1",
        "FencedFinalHoldoutOwnerV1",
    ):
        findings.require(
            token in api_contract,
            "learning_eval_api_contract",
            f"cross-crate API contract does not bind: {token}",
        )


def verify_product_writer_exclusivity(findings: Findings) -> None:
    """Prevent product crates from bypassing LedgerWriter with raw V1 appends."""

    allowed_roots = {
        "codex-rs/hepta-learning-ledger",
        "codex-rs/hepta-shadow-qualification",
    }
    forbidden = {
        r"\bDurableLearningJournal\b": "legacy durable journal trait",
        r"LedgerEvent::Decision\b": "raw V1 Decision append",
        r"LedgerEvent::Outcome\b": "raw V1 Outcome append",
        r"LedgerEvent::Credit\b": "raw V1 Credit append",
        r"LedgerEvent::Revocation\b": "raw V1 Revocation append",
    }

    feature = "qualification-legacy-learning-write"
    manifest = tomllib.loads((ROOT / "codex-rs/hepta-agentd/Cargo.toml").read_text())
    feature_map = manifest.get("features", {})
    pending = list(feature_map.get("default", []))
    reached = set()
    while pending:
        value = pending.pop()
        if value not in reached:
            reached.add(value)
            pending.extend(feature_map.get(value, []))
    disabled = feature not in reached
    # Check the selected repository sources, not ignored build output or test
    # scratch files (including named pipes used by fault-injection fixtures).
    # Untracked source edits remain included; every committed source is included.
    inventory = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z", "--cached", "--others",
         "--exclude-standard", "--", "codex-rs"],
        check=False, capture_output=True, text=True,
    )
    if inventory.returncode:
        findings.require(False, "product_source_inventory", "cannot enumerate current repository source")
        return
    source_paths = [ROOT / name for name in sorted(set(inventory.stdout.split("\0"))) if name]
    regular_paths = []
    for path in source_paths:
        if path.suffix != ".rs" and path.name != "Cargo.toml":
            continue
        try:
            regular = stat.S_ISREG(path.lstat().st_mode)
        except OSError:
            regular = False
        findings.require(regular, "product_source_kind", f"{path.relative_to(ROOT)} is not a regular source file")
        if regular:
            regular_paths.append(path)
    # A downstream normal dependency must not enable the compatibility writer.
    for cargo in (path for path in regular_paths if path.name == "Cargo.toml"):
        document = tomllib.loads(cargo.read_text())
        for section in [document, *document.get("target", {}).values()]:
            for table in ("dependencies", "build-dependencies"):
                for dep in section.get(table, {}).values():
                    if isinstance(dep, dict) and feature in dep.get("features", []):
                        disabled = False
    findings.require(disabled, "legacy_writer_enabled", "legacy learning writer is reachable in a normal dependency or Agentd default")

    for path in (path for path in regular_paths if path.suffix == ".rs"):
        relative = path.relative_to(ROOT).as_posix()
        if any(
            relative == root or relative.startswith(f"{root}/")
            for root in allowed_roots
        ):
            continue
        if (
            "/tests/" in relative
            or path.name.endswith("_tests.rs")
            or path.name.endswith("_test_support.rs")
        ):
            continue

        text = path.read_text(encoding="utf-8")
        if disabled:
            text = without_disabled_feature_items(text, feature)
        for pattern, description in forbidden.items():
            findings.require(
                re.search(pattern, text) is None,
                "legacy_learning_writer_product_bypass",
                f"{relative} uses {description}; product learning writes must use LedgerWriter",
            )


def verify_authority_posture(findings: Findings) -> None:
    sources = [
        ROOT / "codex-rs/hepta-learning-ledger/src/causal_v2.rs",
        ROOT / "codex-rs/hepta-learning-artifacts/src/closure_v2.rs",
        ROOT / "codex-rs/hepta-learning-artifacts/src/publication.rs",
        ROOT / "codex-rs/hepta-learning-artifacts/src/owner_host.rs",
        ROOT / "codex-rs/hepta-learning-artifacts/src/owner_service.rs",
        ROOT / "codex-rs/hepta-learning-artifacts/src/sensor_core_registry.rs",
        ROOT / "codex-rs/hepta-bellman-operator/src/reference.rs",
        ROOT / "codex-rs/hepta-bellman-operator/src/world_model.rs",
        ROOT / "codex-rs/hepta-intelligence-eval/src/closure.rs",
    ]
    for path in sources:
        if not path.is_file():
            findings.add(
                "authority_source_missing", f"missing {path.relative_to(ROOT)}"
            )
            continue
        text = path.read_text(encoding="utf-8")
        findings.require(
            "AuthorityPosture::DENY_ALL" in text,
            "deny_all_missing",
            f"{path.relative_to(ROOT)} does not explicitly emit DENY_ALL authority",
        )


def verify_workflow(findings: Findings) -> None:
    findings.require(
        WORKFLOW_PATH.is_file(),
        "workflow_missing",
        "Lane E exact-head workflow is missing",
    )
    if not WORKFLOW_PATH.is_file():
        return
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    commands = workflow_commands(text)
    test_commands = [
        command
        for command in commands
        if command[:2] in (["cargo", "test"], ["just", "test"])
        and "--locked" in command
    ]
    for crate in EXPECTED_CRATES:
        findings.require(
            any(
                any(
                    command[index : index + 2] in (["-p", crate], ["--package", crate])
                    for index in range(len(command) - 1)
                )
                for command in test_commands
            ),
            "workflow_crate_missing",
            f"workflow does not execute locked tests for {crate}",
        )
    for subcommand in ("check", "clippy"):
        findings.require(
            any(
                command[:2] == ["cargo", subcommand] and "--locked" in command
                for command in commands
            ),
            "workflow_gate_missing",
            f"workflow is missing cargo {subcommand} --locked",
        )
    findings.require(
        any(command[:2] == ["cargo", "fmt"] for command in commands),
        "workflow_gate_missing",
        "workflow is missing cargo fmt",
    )
    findings.require(
        any(
            command[:3] == ["python3", "scripts/hepta-lane-e-closure.py", "verify"]
            for command in commands
        ),
        "workflow_gate_missing",
        "workflow is missing source closure verification",
    )
    findings.require(
        any(
            "lane_e_causal_candidate_chain_is_digest_bound_and_deny_all" in command
            and any(
                command[index : index + 2] == ["-p", "codex-hepta-shadow-qualification"]
                for index in range(len(command) - 1)
            )
            for command in test_commands
        ),
        "workflow_gate_missing",
        "workflow is missing the cross-crate causal regression",
    )
    findings.require(
        any(
            "cross_language_wire_fault" in command
            and any(
                command[index : index + 2] == ["-p", "codex-hepta-shadow-qualification"]
                for index in range(len(command) - 1)
            )
            for command in test_commands
        ),
        "workflow_gate_missing",
        "workflow is missing the cross-language payload-fault regression",
    )
    findings.require(
        bool(re.search(r"^  synthetic-merge:\s*$", text, re.MULTILINE)),
        "workflow_gate_missing",
        "workflow is missing synthetic-merge job",
    )
    for token, message in (
        (
            "learning-eval-qualification:",
            "workflow is missing learning-eval qualification job",
        ),
        (
            "cargo-llvm-cov@0.9.1",
            "workflow is missing pinned learning-eval coverage tooling",
        ),
        ("fenced_holdout", "workflow is missing fenced holdout stress execution"),
        (
            "qualification.json",
            "workflow is missing commit-addressed qualification manifest",
        ),
        (
            "actions/attest-build-provenance@0f67c3f4856b2e3261c31976d6725780e5e4c373",
            "workflow is missing pinned provenance attestation",
        ),
        (
            "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
            "workflow is missing retained qualification artifact",
        ),
        (
            "trusted-inprocess-eval",
            "workflow is missing explicit compatibility-surface verification",
        ),
        (
            "--test operator_claim",
            "workflow is missing the trusted compatibility regression",
        ),
        (
            "decide_with_signed_evidence_v2",
            "workflow is missing signed production-surface verification",
        ),
        (
            "FencedFinalHoldoutOwnerV1",
            "workflow is missing fenced-owner production-surface verification",
        ),
        (
            "ProductEvaluationRunnerV1",
            "workflow is missing product-evaluation production-surface verification",
        ),
        (
            "evaluated_shadow",
            "workflow is missing terminal product-receipt consumer execution",
        ),
        (
            "--fail-under-lines 85",
            "workflow is missing enforced evaluator coverage floor",
        ),
    ):
        findings.require(
            token in text,
            "workflow_gate_missing",
            message,
        )
    findings.require(
        "signed_qualification_e2e" in text
        and "--features trusted-inprocess-eval" in text,
        "learning_eval_workflow_tests",
        "workflow must execute signed E2E and explicit trusted compatibility tests",
    )
    for token in (
        "scripts/hepta-learning-eval-evidence.py emit",
        "scripts/hepta-learning-eval-evidence.py verify",
        "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
        "actions/attest-build-provenance@4d101475d8b20a2381f78447822ac1eab6504dd8",
        "id-token: write",
        "attestations: write",
        "cargo-llvm-cov@0.9.0",
        "--fail-under-lines 85",
        "Adversarial qualification stress",
        "evaluated_shadow",
        "Strict merged Lane E lint",
        "--coverage .hepta-evidence/learning-eval/coverage.json",
        "--stress .hepta-evidence/learning-eval/stress.json",
        "--stress-log .hepta-evidence/learning-eval/stress.log",
        "--runtime-log .hepta-evidence/learning-eval/runtime-e2e.log",
        "github.event.before",
    ):
        findings.require(
            token in text,
            "learning_eval_workflow_evidence",
            f"workflow is missing qualification evidence control: {token}",
        )
    findings.require(
        not TEMPORARY_WORKFLOW_PATH.exists(),
        "temporary_workflow_present",
        "temporary generated-file materializer must not remain in the candidate",
    )


def run_self_test() -> list[Finding]:
    findings = Findings()
    findings.require(
        verify_symbol(
            "pub struct Demo; impl Demo { pub fn execute(&self) {} }",
            "crate::Demo::execute",
        ),
        "self_test_method",
        "method symbol resolver failed",
    )
    findings.require(
        verify_symbol("pub fn execute() {}", "crate::execute"),
        "self_test_function",
        "free-function symbol resolver failed",
    )
    findings.require(
        not verify_symbol("pub fn another() {}", "crate::execute"),
        "self_test_false_positive",
        "symbol resolver accepted a missing function",
    )
    return findings.items


def verify() -> Findings:
    findings = Findings()
    matrix = load_json(MATRIX_PATH, findings)
    trace = load_json(TRACE_PATH, findings)
    modules = verify_matrix(matrix, findings)
    verify_traceability(trace, modules, findings)
    verify_learning_eval_production_boundary(findings)
    verify_product_writer_exclusivity(findings)
    verify_authority_posture(findings)
    verify_workflow(findings)
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=("verify", "self-test"),
        nargs="?",
        default="verify",
    )
    args = parser.parse_args()
    if args.command == "self-test":
        findings = run_self_test()
    else:
        findings = verify().items
    output = {
        "schema": "hepta.lane-e-closure-verification.v1",
        "command": args.command,
        "ok": not findings,
        "findingCount": len(findings),
        "findings": [finding.__dict__ for finding in findings],
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if not findings else 1


if __name__ == "__main__":
    sys.exit(main())
