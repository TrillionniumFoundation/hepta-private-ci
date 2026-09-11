#!/usr/bin/env python3
"""Read-only closed-world verifier for the Lane E implementation candidate."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = ROOT / "docs/lane-e/LANE_E_IMPLEMENTATION_MATRIX.json"
TRACE_PATH = ROOT / "qualification/lane-e/TEST_TRACEABILITY.json"
WORKFLOW_PATH = ROOT / ".github/workflows/hepta-lane-e-gap-closure.yml"
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
    *(f"LEDGER-{index:02d}" for index in range(1, 5)),
    *(f"OP-{index:02d}" for index in range(1, 5)),
    *(f"EVAL-{index:02d}" for index in range(1, 5)),
    *(f"ART-{index:02d}" for index in range(1, 5)),
}
EXPECTED_EXTERNAL_GATES = {f"RDY-EXT-{index:03d}" for index in range(1, 10)}
EXPECTED_OPERATIONS = {
    "learning.ledger": {
        "verify_independent_roles",
        "validate_authenticated_outcome",
        "validate_candidate_set_completeness",
        "finalize_credit_batch",
        "freeze_dataset",
        "append_shadow_decision",
    },
    "learning.artifacts": {
        "validate_artifact_manifest_v2",
        "DatasetWithdrawalRegistry::append",
        "validate_registry_head_witness",
        "validate_artifact_lifecycle_transition",
        "load_pinned_candidate",
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
        "estimate_sequential",
        "freeze_cross_fold_plan",
        "FinalHoldoutRegistry::consume",
        "decide_independently",
    },
}
EXPECTED_CRATES = {
    "codex-hepta-learning-ledger",
    "codex-hepta-learning-artifacts",
    "codex-hepta-bellman-operator",
    "codex-hepta-intelligence-eval",
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
    if not re.search(rf"\b(?:pub\s+)?fn\s+{re.escape(function)}\s*\(", source):
        return False
    if len(parts) >= 2 and parts[-2][:1].isupper():
        owner = parts[-2]
        return bool(
            re.search(rf"\b(?:struct|enum|type)\s+{re.escape(owner)}\b", source)
            and re.search(rf"\bimpl\s+{re.escape(owner)}\b", source)
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
        for key in ("sourceRoot", "stableGuide", "dossier", "nativeMapping"):
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
            findings.require(
                operation.get("status") in {"implemented", "implemented_existing"},
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


def verify_authority_posture(findings: Findings) -> None:
    sources = [
        ROOT / "codex-rs/hepta-learning-ledger/src/causal_v2.rs",
        ROOT / "codex-rs/hepta-learning-artifacts/src/closure_v2.rs",
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


def workflow_commands(text: str) -> list[list[str]]:
    """Read executable run scalars used by this workflow, not comments or labels.

    This deliberately supports the workflow's plain, literal and folded run
    forms. It does not interpret arbitrary shell/YAML programs as proof of tests.
    """
    lines = text.splitlines()
    commands = []
    index = 0
    while index < len(lines):
        match = re.fullmatch(r"(\s*)(?:-\s+)?run:\s*(.*)", lines[index])
        index += 1
        if not match:
            continue
        indent, scalar = match.groups()
        if scalar in ("|", "|-", "|+", ">", ">-", ">+"):
            block = []
            while index < len(lines):
                line = lines[index]
                if line.strip() and len(line) - len(line.lstrip()) <= len(indent):
                    break
                block.append(line.strip())
                index += 1
            scalar = (" " if scalar.startswith(">") else "\n").join(block)
        for line in scalar.replace("\\\n", " ").splitlines():
            try:
                tokens = shlex.split(line, comments=True)
            except ValueError:
                continue
            if tokens:
                commands.append(tokens)
    return commands


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
        bool(re.search(r"^  synthetic-merge:\s*$", text, re.MULTILINE)),
        "workflow_gate_missing",
        "workflow is missing synthetic-merge job",
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
