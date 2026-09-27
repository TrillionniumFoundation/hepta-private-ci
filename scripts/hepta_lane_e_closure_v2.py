#!/usr/bin/env python3
"""Closed-world verifier for the exact Lane E source candidate.

This module deliberately keeps one canonical tool pin and treats qualification,
activation and external acceptance as separate states.  The hyphenated legacy
entry point imports this module so existing workflows keep a stable command.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hepta_workflow_commands import workflow_commands

ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = ROOT / "docs/lane-e/LANE_E_IMPLEMENTATION_MATRIX.json"
TRACE_PATH = ROOT / "qualification/lane-e/TEST_TRACEABILITY.json"
WORKFLOW_PATH = ROOT / ".github/workflows/hepta-lane-e-gap-closure.yml"
BLOCKING_WORKFLOW_PATH = ROOT / ".github/workflows/blocking-ci.yml"
ARTIFACT_MAP_PATH = ROOT / "docs/modules/learning.artifacts/IMPLEMENTATION_MAP.json"
ARTIFACT_STATUS_PATH = ROOT / "qualification/learning-artifacts/STATUS.json"
ARTIFACT_RECEIPT_TOOL = ROOT / "scripts/hepta-learning-artifacts-qualification.py"
PRODUCTION_CONTRACT_PATH = ROOT / "codex-rs/hepta-intelligence-eval/PRODUCTION_CONTRACT.md"
EVIDENCE_SCRIPT_PATH = ROOT / "scripts/hepta-learning-eval-evidence.py"
TEMPORARY_WORKFLOW_PATH = ROOT / ".github/workflows/hepta-lane-e-materialize-generated.yml"

COVERAGE_TOOL_PIN = "cargo-llvm-cov@0.9.0"
EXPECTED_MODULES = {
    "learning.ledger",
    "learning.operator",
    "learning.eval",
    "learning.artifacts",
}
EXPECTED_CASES = {
    *(f"LEDGER-{index:02d}" for index in range(1, 14)),
    *(f"OP-{index:02d}" for index in range(1, 5)),
    *(f"EVAL-{index:02d}" for index in range(1, 8)),
    *(f"ART-{index:02d}" for index in range(1, 13)),
}
EXPECTED_EXTERNAL_GATES = {f"RDY-EXT-{index:03d}" for index in range(1, 10)}
EXPECTED_CRATES = {
    "codex-hepta-learning-ledger",
    "codex-hepta-learning-artifacts",
    "codex-hepta-bellman-operator",
    "codex-hepta-intelligence-eval",
    "codex-hepta-intelligence",
    "codex-hepta-shadow-qualification",
}
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
        "validate_applicability_certificate",
        "build_sensor_core",
        "evaluate_bellman_reference",
        "admit_operator_regularity",
        "fit_transition_model",
        "predict_transition",
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
ALLOWED_OPERATION_STATES = {
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
}


@dataclass(frozen=True)
class Finding:
    code: str
    message: str


class Findings:
    def __init__(self) -> None:
        self.items: list[Finding] = []

    def add(self, code: str, message: str) -> None:
        self.items.append(Finding(code, message))

    def require(self, condition: bool, code: str, message: str) -> None:
        if not condition:
            self.add(code, message)


def load_json(path: Path, findings: Findings) -> dict[str, Any]:
    if not path.is_file():
        findings.add("missing_file", f"missing required file: {path.relative_to(ROOT)}")
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        findings.add("invalid_json", f"cannot parse {path.relative_to(ROOT)}: {error}")
        return {}
    if not isinstance(value, dict):
        findings.add("invalid_json_root", f"{path.relative_to(ROOT)} must be an object")
        return {}
    return value


def repository_path(value: object, findings: Findings, context: str) -> Path | None:
    if not isinstance(value, str) or not value:
        findings.add("invalid_path", f"{context} has no repository path")
        return None
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        findings.add("invalid_path", f"{context} escapes the repository: {value!r}")
        return None
    return ROOT / path


def verify_symbol(source: str, symbol: str) -> bool:
    parts = symbol.split("::")
    name = parts[-1]
    if name[:1].isupper():
        return bool(re.search(rf"\b(?:struct|enum|type|trait)\s+{re.escape(name)}\b", source))
    if not re.search(
        rf"\b(?:pub(?:\([^)]*\))?\s+)?fn\s+{re.escape(name)}"
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


def verify_matrix(matrix: dict[str, Any], findings: Findings) -> dict[str, dict[str, Any]]:
    findings.require(
        matrix.get("schema") == "hepta.lane-e-implementation-matrix.v1",
        "matrix_schema",
        "unexpected Lane E implementation-matrix schema",
    )
    findings.require(matrix.get("authorityDelta") == "none", "authority_delta", "Lane E must grant no authority")
    findings.require(
        matrix.get("capabilityClosureState") == "external_evidence_required",
        "capability_boundary",
        "external capability evidence must remain external",
    )
    raw_modules = matrix.get("modules")
    if not isinstance(raw_modules, list):
        findings.add("matrix_modules", "matrix.modules must be an array")
        return {}
    modules: dict[str, dict[str, Any]] = {}
    for item in raw_modules:
        if not isinstance(item, dict) or not isinstance(item.get("module"), str):
            findings.add("matrix_module", "invalid module record")
            continue
        module = item["module"]
        if module in modules:
            findings.add("duplicate_module", f"duplicate module: {module}")
        modules[module] = item
    findings.require(set(modules) == EXPECTED_MODULES, "module_closed_world", "Lane E module set drifted")

    for module, item in modules.items():
        required_paths = ["sourceRoot", "stableGuide", "dossier", "nativeMapping"]
        if module == "learning.eval":
            required_paths.append("productionContract")
        for key in required_paths:
            path = repository_path(item.get(key), findings, f"{module}.{key}")
            if path is not None:
                findings.require(path.exists(), "matrix_path_missing", f"missing {path.relative_to(ROOT)}")
        findings.require(item.get("remainingRepositoryGaps") == [], "repository_gap_open", f"{module} retains a repository-controlled gap")
        external = item.get("remainingExternalEvidence")
        findings.require(isinstance(external, list) and bool(external), "external_evidence_missing", f"{module} must retain external gates")

        raw_operations = item.get("operations")
        if not isinstance(raw_operations, list):
            findings.add("operations_missing", f"{module}.operations must be an array")
            continue
        operations = {
            operation.get("operation"): operation
            for operation in raw_operations
            if isinstance(operation, dict) and isinstance(operation.get("operation"), str)
        }
        findings.require(set(operations) == EXPECTED_OPERATIONS[module], "operation_closed_world", f"{module} operation set drifted")
        for operation_name, operation in operations.items():
            path = repository_path(operation.get("source"), findings, f"{module}.{operation_name}.source")
            symbol = operation.get("nativeSymbol")
            if path is None or not path.is_file() or not isinstance(symbol, str):
                findings.add("operation_mapping", f"invalid mapping for {module}.{operation_name}")
                continue
            source = path.read_text(encoding="utf-8")
            findings.require(verify_symbol(source, symbol), "native_symbol_unresolved", f"cannot resolve {symbol} in {path.relative_to(ROOT)}")
            findings.require(operation.get("status") in ALLOWED_OPERATION_STATES, "operation_not_implemented", f"{module}.{operation_name} is not source implemented")

    raw_gates = matrix.get("externalGates")
    gates = {
        item.get("id"): item
        for item in raw_gates
        if isinstance(raw_gates, list) and isinstance(item, dict) and isinstance(item.get("id"), str)
    } if isinstance(raw_gates, list) else {}
    findings.require(set(gates) == EXPECTED_EXTERNAL_GATES, "external_gate_closed_world", "external gate set drifted")
    for gate_id, gate in gates.items():
        findings.require(gate.get("repositoryMaySelfCertify") is False, "external_gate_self_certified", f"{gate_id} may not be self-certified")
        state = gate.get("state")
        findings.require(isinstance(state, str) and ("open" in state or "required" in state) and "closed" not in state, "external_gate_false_closure", f"{gate_id} is not open/evidence-required")
    return modules


def verify_traceability(trace: dict[str, Any], modules: dict[str, dict[str, Any]], findings: Findings) -> None:
    findings.require(trace.get("schema") == "hepta.lane-e-test-traceability.v1", "trace_schema", "unexpected traceability schema")
    raw_cases = trace.get("cases")
    if not isinstance(raw_cases, list):
        findings.add("trace_cases", "traceability cases must be an array")
        return
    cases = {
        item.get("id"): item
        for item in raw_cases
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    findings.require(set(cases) == EXPECTED_CASES, "case_closed_world", "Lane E test case set drifted")
    source_cache: dict[Path, str] = {}
    dossier_cache: dict[Path, str] = {}
    for case_id, case in cases.items():
        module = case.get("module")
        findings.require(module in EXPECTED_MODULES, "case_module", f"{case_id} has invalid module")
        if module in modules:
            dossier = repository_path(modules[module].get("dossier"), findings, f"{case_id}.dossier")
            if dossier is not None and dossier.is_file():
                text = dossier_cache.setdefault(dossier, dossier.read_text(encoding="utf-8"))
                findings.require(case_id in text, "dossier_case_missing", f"{case_id} absent from {dossier.relative_to(ROOT)}")
        tests = case.get("tests")
        if not isinstance(tests, list) or not tests:
            findings.add("case_tests_missing", f"{case_id} has no native tests")
            continue
        for index, test in enumerate(tests):
            if not isinstance(test, dict):
                findings.add("test_mapping", f"{case_id}.tests[{index}] is invalid")
                continue
            path = repository_path(test.get("source"), findings, f"{case_id}.tests[{index}].source")
            function = test.get("function")
            if path is None or not path.is_file() or not isinstance(function, str):
                findings.add("test_mapping", f"{case_id}.tests[{index}] is incomplete")
                continue
            source = source_cache.setdefault(path, path.read_text(encoding="utf-8"))
            findings.require(bool(re.search(rf"\bfn\s+{re.escape(function)}\s*\(", source)), "test_function_unresolved", f"{function} absent from {path.relative_to(ROOT)}")
        findings.require(case.get("status") == "native_test_mapped", "case_status", f"{case_id} is not native_test_mapped")

    for field, expected_count in (("crossCrateCases", 1), ("productBoundaryCases", 1)):
        records = trace.get(field)
        findings.require(isinstance(records, list) and len(records) == expected_count, "trace_boundary_count", f"{field} must contain exactly one record")
        if isinstance(records, list):
            for record in records:
                if not isinstance(record, dict):
                    findings.add("trace_boundary_record", f"invalid record in {field}")
                    continue
                path = repository_path(record.get("source"), findings, f"{field}.source")
                function = record.get("function")
                if path is None or not path.is_file() or not isinstance(function, str):
                    findings.add("trace_boundary_record", f"incomplete record in {field}")
                    continue
                text = path.read_text(encoding="utf-8")
                findings.require(bool(re.search(rf"\bfn\s+{re.escape(function)}\s*\(", text)), "trace_boundary_function", f"{function} absent from {path.relative_to(ROOT)}")


def verify_authority_posture(findings: Findings) -> None:
    sources = [
        "codex-rs/hepta-learning-ledger/src/causal_v2.rs",
        "codex-rs/hepta-learning-artifacts/src/closure_v2.rs",
        "codex-rs/hepta-learning-artifacts/src/publication.rs",
        "codex-rs/hepta-learning-artifacts/src/owner_host.rs",
        "codex-rs/hepta-learning-artifacts/src/owner_service.rs",
        "codex-rs/hepta-learning-artifacts/src/sensor_core_registry.rs",
        "codex-rs/hepta-bellman-operator/src/reference.rs",
        "codex-rs/hepta-bellman-operator/src/world_model.rs",
        "codex-rs/hepta-intelligence-eval/src/closure.rs",
    ]
    for relative in sources:
        path = ROOT / relative
        findings.require(path.is_file(), "authority_source_missing", f"missing {relative}")
        if path.is_file():
            findings.require("AuthorityPosture::DENY_ALL" in path.read_text(encoding="utf-8"), "deny_all_missing", f"{relative} lacks explicit DENY_ALL")


def verify_product_writer_exclusivity(findings: Findings) -> None:
    allowed = ("codex-rs/hepta-learning-ledger/", "codex-rs/hepta-shadow-qualification/")
    forbidden = {
        r"\bDurableLearningJournal\b": "legacy durable journal",
        r"LedgerEvent::Decision\b": "raw decision append",
        r"LedgerEvent::Outcome\b": "raw outcome append",
        r"LedgerEvent::Credit\b": "raw credit append",
        r"LedgerEvent::Revocation\b": "raw revocation append",
    }
    for path in (ROOT / "codex-rs").rglob("*.rs"):
        relative = path.relative_to(ROOT).as_posix()
        if relative.startswith(allowed) or "/tests/" in relative or path.name.endswith(("_tests.rs", "_test_support.rs")):
            continue
        text = path.read_text(encoding="utf-8")
        for pattern, description in forbidden.items():
            findings.require(re.search(pattern, text) is None, "legacy_learning_writer_product_bypass", f"{relative} uses {description}")


def verify_learning_eval_boundary(findings: Findings) -> None:
    required = [
        ROOT / "codex-rs/hepta-intelligence-eval/src/lib.rs",
        ROOT / "codex-rs/hepta-intelligence-eval/src/closure.rs",
        ROOT / "codex-rs/hepta-intelligence-eval/src/metric_roles.rs",
        ROOT / "codex-rs/hepta-intelligence-eval/src/fenced_holdout.rs",
        ROOT / "codex-rs/hepta-intelligence-eval/Cargo.toml",
        ROOT / "codex-rs/hepta-shadow-qualification/tests/lane_e_api_contract.rs",
        PRODUCTION_CONTRACT_PATH,
        EVIDENCE_SCRIPT_PATH,
    ]
    for path in required:
        findings.require(path.is_file(), "learning_eval_boundary_file_missing", f"missing {path.relative_to(ROOT)}")
    if not all(path.is_file() for path in required):
        return
    joined = "\n".join(path.read_text(encoding="utf-8") for path in required)
    for token in (
        "trusted-inprocess-eval = []",
        "ProductEvaluationRunnerV1",
        "FencedFinalHoldoutOwnerV1",
        "decide_with_signed_evidence_v2",
        "sourceTree",
        "qualificationOutputs",
        "lineCoverageThresholdPct",
        "stressIterations",
        "DENY_ALL",
    ):
        findings.require(token in joined, "learning_eval_boundary", f"missing learning.eval boundary token: {token}")


def verify_workflows(findings: Findings) -> None:
    findings.require(WORKFLOW_PATH.is_file(), "workflow_missing", "Lane E workflow is missing")
    findings.require(BLOCKING_WORKFLOW_PATH.is_file(), "workflow_missing", "blocking CI workflow is missing")
    if not WORKFLOW_PATH.is_file():
        return
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    commands = workflow_commands(text)
    test_commands = [command for command in commands if command[:2] in (["cargo", "test"], ["just", "test"]) and "--locked" in command]
    for crate in EXPECTED_CRATES:
        findings.require(any(any(command[index:index + 2] in (["-p", crate], ["--package", crate]) for index in range(len(command) - 1)) for command in test_commands), "workflow_crate_missing", f"workflow does not test {crate}")
    for subcommand in ("check", "clippy"):
        findings.require(any(command[:2] == ["cargo", subcommand] and "--locked" in command for command in commands), "workflow_gate_missing", f"workflow lacks cargo {subcommand} --locked")
    findings.require(any(command[:2] == ["cargo", "fmt"] for command in commands), "workflow_gate_missing", "workflow lacks cargo fmt")
    pins = set(re.findall(r"cargo-llvm-cov@[0-9]+(?:\.[0-9]+){2}", text))
    findings.require(pins == {COVERAGE_TOOL_PIN}, "coverage_pin_drift", f"coverage tool pins must be exactly {COVERAGE_TOOL_PIN}; found {sorted(pins)}")
    for token in (
        "python3 scripts/hepta-lane-e-closure.py verify",
        "lane_e_causal_candidate_chain_is_digest_bound_and_deny_all",
        "cross_language_wire_fault",
        "synthetic-merge:",
        "learning-eval-qualification:",
        "signed_qualification_e2e",
        "trusted-inprocess-eval",
        "evaluated_shadow",
        "--fail-under-lines 85",
        "scripts/hepta-learning-eval-evidence.py emit",
        "scripts/hepta-learning-eval-evidence.py verify",
        "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
        "actions/attest-build-provenance@4d101475d8b20a2381f78447822ac1eab6504dd8",
        "github.event.before",
    ):
        findings.require(token in text, "workflow_gate_missing", f"Lane E workflow lacks {token}")
    findings.require(not TEMPORARY_WORKFLOW_PATH.exists(), "temporary_workflow_present", "temporary materializer workflow remains")

    if BLOCKING_WORKFLOW_PATH.is_file():
        blocking = BLOCKING_WORKFLOW_PATH.read_text(encoding="utf-8")
        for token in (
            "learning-artifacts-qualification:",
            "hepta-learning-artifacts-qualification.py run-task",
            "hepta-learning-artifacts-qualification.py emit",
            "hepta-learning-artifacts-qualification.py verify",
            "- learning-artifacts-qualification",
        ):
            findings.require(token in blocking, "blocking_ci_artifact_gate", f"CI required is not bound to {token}")


def verify_artifact_claim_state(findings: Findings) -> None:
    implementation = load_json(ARTIFACT_MAP_PATH, findings)
    status = load_json(ARTIFACT_STATUS_PATH, findings)
    findings.require(ARTIFACT_RECEIPT_TOOL.is_file(), "artifact_receipt_tool_missing", "learning.artifacts qualification receipt tool is missing")
    findings.require(implementation.get("module") == "learning.artifacts", "artifact_map_module", "wrong learning.artifacts implementation map")
    claim = implementation.get("claimBoundary")
    findings.require(isinstance(claim, dict), "artifact_claim_boundary", "claimBoundary must be explicit")
    if isinstance(claim, dict):
        for key in ("productExecutionProved", "independentAcceptance", "activation", "release"):
            findings.require(claim.get(key) is False, "artifact_false_completion", f"{key} may not be true in source mapping")
    findings.require(implementation.get("productionImplementation") is False, "artifact_false_completion", "source map may not claim production implementation")
    serialized = json.dumps(implementation, sort_keys=True)
    findings.require('"COMPLETE"' not in serialized and '"complete"' not in serialized, "artifact_unified_complete", "implementation map may not expose a unified COMPLETE state")
    findings.require(status.get("schema") == "hepta.learning-artifacts-qualification-status.v1", "artifact_status_schema", "unexpected learning.artifacts status schema")
    dimensions = status.get("dimensions")
    findings.require(isinstance(dimensions, dict), "artifact_status_dimensions", "qualification dimensions are missing")
    if isinstance(dimensions, dict):
        findings.require(dimensions.get("sourceImplementation") == "implemented", "artifact_status_source", "source implementation must be explicit")
        findings.require(dimensions.get("exactHeadQualification") == "pending_current_candidate", "artifact_status_exact_head", "committed status must not pre-claim its own exact-head pass")
        for key in ("productionActivation", "independentAcceptance", "release"):
            findings.require(dimensions.get(key) == "external_not_established", "artifact_status_external", f"{key} must remain external")
    findings.require(status.get("unifiedComplete") is False, "artifact_unified_complete", "unifiedComplete must remain false")


def run_self_test() -> list[Finding]:
    findings = Findings()
    findings.require(verify_symbol("pub struct Demo; impl Demo { pub fn execute(&self) {} }", "crate::Demo::execute"), "self_test_method", "method symbol resolver failed")
    findings.require(verify_symbol("pub fn execute() {}", "crate::execute"), "self_test_function", "function symbol resolver failed")
    findings.require(not verify_symbol("pub fn another() {}", "crate::execute"), "self_test_false_positive", "missing symbol was accepted")
    findings.require(COVERAGE_TOOL_PIN == "cargo-llvm-cov@0.9.0", "self_test_pin", "canonical coverage pin changed without review")
    return findings.items


def verify() -> Findings:
    findings = Findings()
    modules = verify_matrix(load_json(MATRIX_PATH, findings), findings)
    verify_traceability(load_json(TRACE_PATH, findings), modules, findings)
    verify_learning_eval_boundary(findings)
    verify_product_writer_exclusivity(findings)
    verify_authority_posture(findings)
    verify_workflows(findings)
    verify_artifact_claim_state(findings)
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "self-test"), nargs="?", default="verify")
    args = parser.parse_args()
    findings = run_self_test() if args.command == "self-test" else verify().items
    output = {
        "schema": "hepta.lane-e-closure-verification.v2",
        "command": args.command,
        "coverageToolPin": COVERAGE_TOOL_PIN,
        "ok": not findings,
        "findingCount": len(findings),
        "findings": [finding.__dict__ for finding in findings],
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if not findings else 1


if __name__ == "__main__":
    sys.exit(main())
