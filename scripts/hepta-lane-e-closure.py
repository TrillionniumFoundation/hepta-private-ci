#!/usr/bin/env python3
"""Read-only closed-world verifier for the Lane E implementation candidate."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = ROOT / "docs/lane-e/LANE_E_IMPLEMENTATION_MATRIX.json"
STATUS_PATH = ROOT / "docs/lane-e/LANE_E_STATUS.json"
TRACE_PATH = ROOT / "qualification/lane-e/TEST_TRACEABILITY.json"
WORKFLOW_PATH = ROOT / ".github/workflows/hepta-lane-e-gap-closure.yml"
TEMPORARY_WORKFLOW_PATH = ROOT / ".github/workflows/hepta-lane-e-materialize-generated.yml"
API_CONTRACT_PATH = (
    ROOT / "codex-rs/hepta-shadow-qualification/tests/lane_e_api_contract.rs"
)

EXPECTED_MODULES = {
    "learning.ledger",
    "learning.operator",
    "learning.eval",
    "learning.artifacts",
}
EXPECTED_CASES = {
    *(f"LEDGER-{index:02d}" for index in range(1, 6)),
    *(f"OP-{index:02d}" for index in range(1, 6)),
    *(f"EVAL-{index:02d}" for index in range(1, 6)),
    *(f"ART-{index:02d}" for index in range(1, 7)),
}
EXPECTED_CROSS_CASES = {"LANE-E-E2E-01", "LANE-E-API-01"}
EXPECTED_EXTERNAL_GATES = {f"RDY-EXT-{index:03d}" for index in range(1, 10)}
EXPECTED_OPERATIONS = {
    "learning.ledger": {
        "verify_independent_roles",
        "validate_authenticated_outcome",
        "validate_candidate_set_completeness",
        "finalize_credit_batch",
        "freeze_dataset",
        "append_shadow_decision",
        "freeze_dataset_receipt_v3",
        "verify_dataset_snapshot_receipt_v3",
    },
    "learning.operator": {
        "build_targets",
        "validate_applicability_certificate",
        "build_sensor_core",
        "evaluate_bellman_reference",
        "admit_operator_regularity",
        "fit_transition_model",
        "predict_transition",
        "fit_tabular_operator",
        "predict_tabular_operator",
        "fit_tabular_operator_strict_v2",
        "predict_tabular_operator_indexed_v2",
    },
    "learning.eval": {
        "estimate_ope",
        "estimate_cluster_intervals",
        "estimate_sequential",
        "fit_temporal_fold",
        "evaluate_temporal_holdout",
        "freeze_cross_fold_plan",
        "FinalHoldoutRegistry::consume",
        "decide_independently",
        "FinalHoldoutJournalV1::consume",
        "FinalHoldoutJournalV1::from_snapshot",
    },
    "learning.artifacts": {
        "write_candidate_payload",
        "write_registry_snapshot",
        "read_candidate_payload",
        "read_registry_snapshot",
        "validate_artifact_manifest_v2",
        "DatasetWithdrawalRegistry::append",
        "DatasetWithdrawalRegistry::admit_manifest",
        "validate_registry_head_witness",
        "validate_artifact_lifecycle_transition",
        "load_pinned_candidate",
        "admit_manifest_at_withdrawal_head_v3",
        "validate_artifact_publication_v3",
        "verify_artifact_admission_v3",
        "ArtifactLifecycleJournalV2::append",
        "ArtifactLifecycleJournalV2::from_snapshot",
    },
}
EXPECTED_CRATES = {
    "codex-hepta-learning-ledger",
    "codex-hepta-learning-artifacts",
    "codex-hepta-bellman-operator",
    "codex-hepta-intelligence-eval",
    "codex-hepta-shadow-qualification",
}
EXPECTED_WORKFLOW_PATHS = {
    "docs/lane-e/**",
    "docs/modules/learning.ledger/**",
    "docs/modules/learning.operator/**",
    "docs/modules/learning.eval/**",
    "docs/modules/learning.artifacts/**",
    "qualification/lane-e/**",
    "qualification/module-execution-dossiers/detail/learning.ledger.md",
    "qualification/module-execution-dossiers/detail/learning.operator.md",
    "qualification/module-execution-dossiers/detail/learning.eval.md",
    "qualification/module-execution-dossiers/detail/learning.artifacts.md",
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
        findings.add("missing_file", f"missing required JSON: {path.relative_to(ROOT)}")
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
    if not isinstance(value, str) or not value or value.startswith(("/", "../")):
        findings.add("invalid_path", f"{context} has invalid path: {value!r}")
        return None
    path = Path(value)
    if ".." in path.parts:
        findings.add("invalid_path", f"{context} escapes repository: {value!r}")
        return None
    return ROOT / path


def strip_rust_comments(source: str) -> str:
    without_blocks = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", without_blocks)


def has_public_symbol(source: str, native_symbol: str) -> bool:
    clean = strip_rust_comments(source)
    parts = native_symbol.split("::")
    function = parts[-1]
    function_pattern = re.compile(
        rf"\bpub\s+(?:(?:async|const|unsafe)\s+)*fn\s+{re.escape(function)}\s*\("
    )
    if function_pattern.search(clean) is None:
        return False
    if len(parts) >= 2 and parts[-2][:1].isupper():
        owner = parts[-2]
        owner_declared = re.search(
            rf"\bpub\s+(?:struct|enum|type)\s+{re.escape(owner)}\b", clean
        )
        owner_impl = re.search(rf"\bimpl(?:<[^>]+>)?\s+{re.escape(owner)}\b", clean)
        return owner_declared is not None and owner_impl is not None
    return True


def has_test_function(source: str, function: str) -> bool:
    clean = strip_rust_comments(source)
    pattern = re.compile(
        rf"#\s*\[\s*(?:(?:tokio|rstest)::)?test(?:\s*\([^\]]*\))?\s*\]"
        rf"(?:\s*#\s*\[[^\]]+\])*\s*(?:pub\s+)?(?:async\s+)?fn\s+"
        rf"{re.escape(function)}\s*\("
    )
    return pattern.search(clean) is not None


def api_contract_symbols(source: str) -> set[str]:
    clean = strip_rust_comments(source)
    return set(
        re.findall(
            r"\blet\s+_\s*=\s*([A-Za-z_][A-Za-z0-9_:]*)\s*;",
            clean,
        )
    )


def verify_status(status: dict[str, Any], findings: Findings) -> None:
    findings.require(
        status.get("schema") == "hepta.lane-e-status.v2",
        "status_schema",
        "unexpected Lane E status schema",
    )
    findings.require(
        status.get("authorityDelta") == "none",
        "status_authority_delta",
        "Lane E status must retain zero authority delta",
    )
    findings.require(
        status.get("repositoryControlledGaps") == [],
        "status_repository_gap",
        "canonical status still lists a repository-controlled gap",
    )
    source_identity = status.get("sourceIdentity")
    findings.require(
        isinstance(source_identity, dict)
        and source_identity.get("mutableBranchAsQualificationTarget") is False,
        "status_mutable_target",
        "qualification may not use a mutable branch as its target",
    )
    stages = status.get("stages")
    required_stages = {
        "documentedTarget",
        "sourceImplemented",
        "apiAndTestMapped",
        "sourceQualifiedExactHead",
        "sourceQualifiedSyntheticMerge",
        "productWired",
        "independentlyAccepted",
        "runtimeActivated",
        "longitudinallyValidated",
    }
    findings.require(
        isinstance(stages, dict) and set(stages) == required_stages,
        "status_stage_closed_world",
        "canonical Lane E stage set is incomplete or contains undeclared stages",
    )
    external = status.get("externalEvidenceGates")
    findings.require(
        isinstance(external, list) and len(external) == 8,
        "status_external_gates",
        "canonical status must retain external gates RDY-EXT-002 through RDY-EXT-009",
    )


def verify_matrix(
    matrix: dict[str, Any], findings: Findings
) -> dict[str, dict[str, Any]]:
    findings.require(
        matrix.get("schema") == "hepta.lane-e-implementation-matrix.v2",
        "matrix_schema",
        "unexpected Lane E matrix schema",
    )
    findings.require(
        matrix.get("authorityDelta") == "none",
        "matrix_authority_delta",
        "Lane E matrix must retain zero authority delta",
    )
    findings.require(
        matrix.get("capabilityClosureState") == "external_evidence_required",
        "matrix_truth_boundary",
        "capability closure must remain external-evidence-required",
    )
    base_commit = matrix.get("baseCommit")
    findings.require(
        isinstance(base_commit, str) and re.fullmatch(r"[0-9a-f]{40}", base_commit) is not None,
        "matrix_base_commit",
        "matrix baseCommit must be an immutable forty-character SHA",
    )
    status_path = repository_path(matrix.get("canonicalStatus"), findings, "canonicalStatus")
    if status_path is not None:
        findings.require(status_path.is_file(), "matrix_status_path", "canonical status is missing")

    modules_raw = matrix.get("modules")
    if not isinstance(modules_raw, list):
        findings.add("matrix_modules", "matrix modules must be an array")
        return {}
    modules: dict[str, dict[str, Any]] = {}
    for item in modules_raw:
        if not isinstance(item, dict) or not isinstance(item.get("module"), str):
            findings.add("matrix_module_record", "matrix contains an invalid module record")
            continue
        module = item["module"]
        if module in modules:
            findings.add("duplicate_module", f"duplicate module: {module}")
            continue
        modules[module] = item

    findings.require(
        set(modules) == EXPECTED_MODULES,
        "module_closed_world",
        f"matrix modules must be exactly {sorted(EXPECTED_MODULES)}",
    )
    expected_api_symbols: set[str] = set()
    api_text = (
        API_CONTRACT_PATH.read_text(encoding="utf-8")
        if API_CONTRACT_PATH.is_file()
        else ""
    )
    for module, item in modules.items():
        findings.require(
            "supplementalOperations" not in item,
            "supplemental_operation_bypass",
            f"{module} may not hide operations in supplementalOperations",
        )
        resolved_paths: dict[str, Path] = {}
        for key in ("sourceRoot", "crateRoot", "stableGuide", "dossier", "nativeMapping"):
            path = repository_path(item.get(key), findings, f"{module}.{key}")
            if path is not None:
                resolved_paths[key] = path
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
            f"{module} must retain applicable external evidence",
        )

        operations_raw = item.get("operations")
        if not isinstance(operations_raw, list):
            findings.add("operations_missing", f"{module} has no operations array")
            continue
        operations: dict[str, dict[str, Any]] = {}
        for operation in operations_raw:
            if not isinstance(operation, dict) or not isinstance(operation.get("operation"), str):
                findings.add("invalid_operation", f"{module} has an invalid operation record")
                continue
            name = operation["operation"]
            if name in operations:
                findings.add("duplicate_operation", f"duplicate operation: {module}.{name}")
                continue
            operations[name] = operation
        findings.require(
            set(operations) == EXPECTED_OPERATIONS[module],
            "operation_closed_world",
            f"{module} operation set differs from the required closed world",
        )

        crate_root = resolved_paths.get("crateRoot")
        crate_text = (
            crate_root.read_text(encoding="utf-8")
            if crate_root is not None and crate_root.is_file()
            else ""
        )
        for operation_name, operation in operations.items():
            source_path = repository_path(
                operation.get("source"), findings, f"{module}.{operation_name}.source"
            )
            symbol = operation.get("nativeSymbol")
            if source_path is None or not source_path.is_file():
                findings.add("operation_source_missing", f"missing source for {module}.{operation_name}")
                continue
            if not isinstance(symbol, str):
                findings.add("native_symbol_missing", f"missing symbol for {module}.{operation_name}")
                continue
            expected_api_symbols.add(symbol)
            source = source_path.read_text(encoding="utf-8")
            findings.require(
                has_public_symbol(source, symbol),
                "native_symbol_unresolved",
                f"cannot resolve public {symbol} in {source_path.relative_to(ROOT)}",
            )
            export_token = symbol.split("::")[-2] if "::" in operation_name else symbol.split("::")[-1]
            findings.require(
                bool(re.search(rf"\b{re.escape(export_token)}\b", crate_text)),
                "native_symbol_not_exported",
                f"{symbol} is not visible from {crate_root.relative_to(ROOT) if crate_root else 'crate root'}",
            )
            findings.require(
                operation.get("status") in {"implemented", "implemented_existing"},
                "operation_not_implemented",
                f"{module}.{operation_name} is not source-implemented",
            )
            findings.require(
                symbol in api_text,
                "api_contract_missing_symbol",
                f"cross-crate API contract omits {symbol}",
            )

    findings.require(
        api_contract_symbols(api_text) == expected_api_symbols,
        "api_contract_closed_world",
        "cross-crate API contract symbols differ from the implementation matrix",
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
        findings.add("cross_crate_missing", "cross-crate qualification record is missing")
    else:
        for source_key, test_key in (
            ("source", "test"),
            ("apiContractSource", "apiContractTest"),
        ):
            path = repository_path(cross.get(source_key), findings, f"cross.{source_key}")
            function = cross.get(test_key)
            if path is None or not path.is_file() or not isinstance(function, str):
                findings.add("cross_crate_source", f"invalid cross-crate mapping: {source_key}")
                continue
            findings.require(
                has_test_function(path.read_text(encoding="utf-8"), function),
                "cross_crate_test_missing",
                f"cross-crate test is missing or lacks test attribute: {function}",
            )
    return modules


def verify_traceability(
    trace: dict[str, Any], modules: dict[str, dict[str, Any]], findings: Findings
) -> None:
    findings.require(
        trace.get("schema") == "hepta.lane-e-test-traceability.v2",
        "trace_schema",
        "unexpected Lane E traceability schema",
    )
    findings.require(
        trace.get("authorityDelta") == "none",
        "trace_authority_delta",
        "Lane E traceability must retain zero authority delta",
    )
    findings.require(
        trace.get("exactHeadWorkflow") == ".github/workflows/hepta-lane-e-gap-closure.yml",
        "trace_workflow",
        "traceability must bind the canonical Lane E workflow",
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
    traced_functions: set[str] = set()
    for case_id, case in cases.items():
        module = case.get("module")
        findings.require(
            module in EXPECTED_MODULES,
            "case_module",
            f"{case_id} has invalid module {module!r}",
        )
        if module in modules:
            dossier = repository_path(modules[module].get("dossier"), findings, f"{case_id}.dossier")
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
            source_path = repository_path(test.get("source"), findings, f"{context}.source")
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
                has_test_function(source_text, function),
                "test_function_unresolved",
                f"{function} is absent or lacks a test attribute in {source_path.relative_to(ROOT)}",
            )
            traced_functions.add(function)
        findings.require(
            case.get("status") == "native_test_mapped",
            "case_status",
            f"{case_id} is not marked native_test_mapped",
        )

    for module, item in modules.items():
        listed = item.get("tests")
        if isinstance(listed, list):
            missing = sorted(set(listed) - traced_functions)
            findings.require(
                not missing,
                "matrix_test_not_traced",
                f"{module} matrix tests missing from traceability: {missing}",
            )

    cross_raw = trace.get("crossCrateCases")
    cross: dict[str, dict[str, Any]] = {}
    if isinstance(cross_raw, list):
        for item in cross_raw:
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                cross[item["id"]] = item
    findings.require(
        set(cross) == EXPECTED_CROSS_CASES,
        "cross_case_closed_world",
        f"cross-crate cases must be exactly {sorted(EXPECTED_CROSS_CASES)}",
    )
    for case_id, item in cross.items():
        source_path = repository_path(item.get("source"), findings, f"{case_id}.source")
        function = item.get("function")
        if source_path is None or not source_path.is_file() or not isinstance(function, str):
            findings.add("invalid_cross_case", f"invalid cross-crate case: {case_id}")
            continue
        findings.require(
            has_test_function(source_path.read_text(encoding="utf-8"), function),
            "cross_case_unresolved",
            f"cross-crate function is missing or lacks test attribute: {function}",
        )


def verify_authority_posture(findings: Findings) -> None:
    sources = [
        ROOT / "codex-rs/hepta-learning-ledger/src/causal_v2.rs",
        ROOT / "codex-rs/hepta-learning-ledger/src/dataset_receipt_v3.rs",
        ROOT / "codex-rs/hepta-learning-artifacts/src/closure_v2.rs",
        ROOT / "codex-rs/hepta-learning-artifacts/src/admission_v3.rs",
        ROOT / "codex-rs/hepta-learning-artifacts/src/lifecycle_journal.rs",
        ROOT / "codex-rs/hepta-bellman-operator/src/reference.rs",
        ROOT / "codex-rs/hepta-bellman-operator/src/world_model.rs",
        ROOT / "codex-rs/hepta-bellman-operator/src/learned.rs",
        ROOT / "codex-rs/hepta-bellman-operator/src/learned_strict.rs",
        ROOT / "codex-rs/hepta-intelligence-eval/src/closure.rs",
        ROOT / "codex-rs/hepta-intelligence-eval/src/holdout_journal.rs",
    ]
    for path in sources:
        if not path.is_file():
            findings.add("authority_source_missing", f"missing {path.relative_to(ROOT)}")
            continue
        findings.require(
            "AuthorityPosture::DENY_ALL" in path.read_text(encoding="utf-8"),
            "deny_all_missing",
            f"{path.relative_to(ROOT)} does not explicitly retain DENY_ALL authority",
        )


def verify_workflow(findings: Findings) -> None:
    findings.require(WORKFLOW_PATH.is_file(), "workflow_missing", "Lane E workflow is missing")
    if not WORKFLOW_PATH.is_file():
        return
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    for crate in EXPECTED_CRATES:
        findings.require(
            crate in text,
            "workflow_crate_missing",
            f"workflow does not qualify {crate}",
        )
    for token in (
        "cargo check --locked",
        "cargo test --locked",
        "cargo clippy --locked",
        "cargo fmt",
        "scripts/hepta-lane-e-closure.py",
        "synthetic-merge",
        "github.event.pull_request.base.sha",
        "PR_BASE_SHA",
        "git merge-base",
    ):
        findings.require(
            token in text,
            "workflow_gate_missing",
            f"workflow is missing required token: {token}",
        )
    for path in EXPECTED_WORKFLOW_PATHS:
        findings.require(
            path in text,
            "workflow_path_missing",
            f"workflow paths filter omits {path}",
        )
    findings.require(
        "TARGET_BRANCH" not in text and "codex/hepta-main-convergence" not in text,
        "workflow_mutable_target",
        "workflow still uses a mutable qualification target",
    )
    findings.require(
        not TEMPORARY_WORKFLOW_PATH.exists(),
        "temporary_workflow_present",
        "temporary generated-file materializer must not remain in the candidate",
    )


def run_self_test() -> list[Finding]:
    findings = Findings()
    public_source = "pub struct Demo; impl Demo { pub fn execute(&self) {} }"
    findings.require(
        has_public_symbol(public_source, "crate::Demo::execute"),
        "self_test_method",
        "public method resolver failed",
    )
    findings.require(
        has_public_symbol("pub fn execute() {}", "crate::execute"),
        "self_test_function",
        "public function resolver failed",
    )
    findings.require(
        not has_public_symbol("fn execute() {}", "crate::execute"),
        "self_test_private",
        "private function was accepted as public",
    )
    findings.require(
        has_test_function("#[test]\nfn works() {}", "works"),
        "self_test_test_attribute",
        "test attribute resolver failed",
    )
    findings.require(
        not has_test_function("fn works() {}", "works"),
        "self_test_non_test",
        "plain function was accepted as a test",
    )
    findings.require(
        api_contract_symbols("let _ = crate::Demo::execute;")
        == {"crate::Demo::execute"},
        "self_test_api_contract",
        "API contract symbol extraction failed",
    )
    return findings.items


def verify() -> Findings:
    findings = Findings()
    matrix = load_json(MATRIX_PATH, findings)
    status = load_json(STATUS_PATH, findings)
    trace = load_json(TRACE_PATH, findings)
    findings.require(API_CONTRACT_PATH.is_file(), "api_contract_missing", "API contract test is missing")
    verify_status(status, findings)
    modules = verify_matrix(matrix, findings)
    verify_traceability(trace, modules, findings)
    verify_authority_posture(findings)
    verify_workflow(findings)
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "self-test"), nargs="?", default="verify")
    args = parser.parse_args()
    findings = run_self_test() if args.command == "self-test" else verify().items
    output = {
        "schema": "hepta.lane-e-closure-verification.v2",
        "command": args.command,
        "ok": not findings,
        "findingCount": len(findings),
        "findings": [asdict(finding) for finding in findings],
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
