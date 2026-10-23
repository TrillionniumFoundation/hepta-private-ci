#!/usr/bin/env python3
"""Read-only closed-world verifier for the Lane E implementation candidate."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from hepta_module_registry import load_module_registry
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
EXPECTED_EXTERNAL_GATES = {f"RDY-EXT-{index:03d}" for index in range(1, 10)}
EXPECTED_CRATES = {
    "codex-hepta-learning-ledger",
    "codex-hepta-learning-artifacts",
    "codex-hepta-bellman-operator",
    "codex-hepta-intelligence-eval",
    "codex-hepta-intelligence",
    "codex-hepta-shadow-qualification",
}


# Reuse the repository's bounded lexical inventory for API navigation. Actual
# Rust compilation and signed/holdout regressions remain qualification gates.
_SOURCE_SPEC = importlib.util.spec_from_file_location(
    "lane_e_source_inventory", ROOT / "scripts/hepta-implementation-maps.py"
)
assert _SOURCE_SPEC is not None and _SOURCE_SPEC.loader is not None
_SOURCE_INVENTORY = importlib.util.module_from_spec(_SOURCE_SPEC)
_SOURCE_SPEC.loader.exec_module(_SOURCE_INVENTORY)


def unsigned_root_exports(source: str) -> set[str]:
    # Use-tree braces group imported names, not nested item scopes. Preserve
    # their tokens before the shared inventory masks actual nested modules.
    source = re.sub(
        r"\bpub\s+use\s+[^;]+;",
        lambda match: match.group().replace("{", " ").replace("}", " "),
        source,
    )
    source = _SOURCE_INVENTORY.top_level_rust_source(source)
    forbidden = {
        "evaluate",
        "decide_independently",
        "decide_independently_v2",
        "decide_with_signed_evidence_v1",
    }
    declarations = re.findall(
        r"\bpub\s+(?:(?:async|const|unsafe)\s+)*fn\s+(\w+)\b", source
    )
    exposed = forbidden.intersection(declarations)
    for declaration in re.findall(r"\bpub\s+use\s+([^;]+);", source):
        exposed.update(forbidden.intersection(re.findall(r"\b\w+\b", declaration)))
        if "*" in declaration and re.search(
            r"\b(?:closure|metric_roles)\b", declaration
        ):
            exposed.add("unsigned_wildcard")
    return exposed


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
    try:
        relative = path.relative_to(ROOT).as_posix()
    except ValueError:
        findings.add("invalid_path", f"JSON registry escapes the repository: {path}")
        return {}
    checked = relative_path(relative, findings, "JSON registry")
    if checked is None:
        return {}
    path = checked
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
    try:
        # Use the implementation-map inventory's existing canonical path
        # contract: reject every symlink component before reading owner source.
        return _SOURCE_INVENTORY.checked_source_path(ROOT, value)
    except ValueError as error:
        findings.add(
            "invalid_path", f"{context} has invalid repository path: {value!r}: {error}"
        )
        return None


def verify_symbol(source: str, native_symbol: str) -> bool:
    # The navigation schema names identifier paths; unsupported Rust type/UFCS
    # expressions must not fall back to finding an unrelated free function.
    if not re.fullmatch(r"[A-Za-z_]\w*(?:::[A-Za-z_]\w*)*", native_symbol):
        return False
    source = rust_code(source)
    top_level = _SOURCE_INVENTORY.top_level_rust_source(source)
    parts = native_symbol.split("::")
    function = parts[-1]
    function_pattern = (
        rf"\b(?:pub(?:\([^)]*\))?\s+)?fn\s+{re.escape(function)}"
        rf"(?:\s*<[^{{}};]*>)?\s*\("
    )
    if function[:1].isupper():
        return bool(
            re.search(
                rf"\b(?:struct|enum|type|trait)\s+{re.escape(function)}\b", top_level
            )
        )
    if len(parts) >= 2 and parts[-2][:1].isupper():
        owner = parts[-2]
        if not re.search(rf"\b(?:struct|enum|type)\s+{re.escape(owner)}\b", top_level):
            return False
        for implementation in re.finditer(
            rf"\bimpl(?:\s*<[^{{}};]*>)?\s+{re.escape(owner)}\b[^{{}};]*\{{",
            source,
        ):
            if top_level[implementation.start()] != "i":
                continue
            start = cursor = implementation.end()
            depth = 1
            while cursor < len(source) and depth:
                if source[cursor] == "{":
                    depth += 1
                elif source[cursor] == "}":
                    depth -= 1
                cursor += 1
            if depth:
                continue
            # A free function, another type's method, or a nested local helper
            # cannot satisfy this type's associated-method navigation binding.
            body = _SOURCE_INVENTORY.top_level_rust_source(source[start : cursor - 1])
            if re.search(function_pattern, body):
                return True
        return False
    return bool(re.search(function_pattern, top_level))


def registered_operations(findings: Findings) -> dict[str, dict[str, dict[str, Any]]]:
    """Load the versioned Lane E subset, rather than freeze implementation-map APIs.

    The canonical matrix registers Lane E operation identities and their exact
    source/symbol bindings. Broader module implementation maps may contain other
    owner operations and product consumers. Independently supplied matrix input
    must preserve this registry; actual source and canonical ownership are
    checked separately and this navigation registry grants no runtime authority.
    """
    registered: dict[str, dict[str, dict[str, Any]]] = {}
    matrix = load_json(MATRIX_PATH, findings)
    rows = matrix.get("modules")
    if not isinstance(rows, list):
        findings.add(
            "canonical_operation_registry_invalid", "missing registered modules"
        )
        return registered
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("module"), str):
            findings.add(
                "canonical_operation_registry_invalid", "invalid registered module"
            )
            continue
        module = row["module"]
        operations = row.get("operations")
        if module in registered or not isinstance(operations, list) or not operations:
            findings.add(
                "canonical_operation_registry_invalid", f"invalid registry for {module}"
            )
            continue
        registered[module] = {}
        for operation in operations:
            if not isinstance(operation, dict):
                findings.add(
                    "canonical_operation_registry_invalid",
                    f"invalid operation for {module}",
                )
                continue
            name = operation.get("operation")
            if (
                not isinstance(name, str)
                or not name.strip()
                or name in registered[module]
                or not isinstance(operation.get("source"), str)
                or not isinstance(operation.get("nativeSymbol"), str)
            ):
                findings.add(
                    "canonical_operation_registry_invalid",
                    f"invalid operation identity for {module}",
                )
                continue
            registered[module][name] = operation
    findings.require(
        set(registered) == EXPECTED_MODULES,
        "canonical_operation_registry_invalid",
        "Lane E operation registry has an unknown or missing module",
    )
    return registered


def registered_cases(findings: Findings) -> dict[str, str]:
    """Read required case identities from canonical module execution dossiers."""
    cases: dict[str, str] = {}
    for module in sorted(EXPECTED_MODULES):
        try:
            path = _SOURCE_INVENTORY.checked_source_path(
                ROOT, f"qualification/module-execution-dossiers/detail/{module}.md"
            )
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError, ValueError) as error:
            findings.add(
                "canonical_case_registry_invalid",
                f"cannot read {module} dossier: {error}",
            )
            continue
        identities = re.findall(
            r"^\s*-\s+`?([A-Z][A-Z0-9]*-\d+)`?\s*:", text, re.MULTILINE
        )
        findings.require(
            bool(identities),
            "canonical_case_registry_invalid",
            f"{module} dossier has no concrete verification cases",
        )
        for identity in identities:
            if identity in cases:
                findings.add(
                    "canonical_case_registry_invalid",
                    f"duplicate dossier case: {identity}",
                )
                continue
            cases[identity] = module
    return cases


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
    try:
        registered = {
            row["id"]: row
            for row in load_module_registry(
                _SOURCE_INVENTORY.checked_source_path(ROOT, "docs/modules/MODULES.json")
            )
        }
    except (OSError, ValueError) as error:
        findings.add("canonical_registry_invalid", str(error))
        registered = {}
    operation_registry = registered_operations(findings)
    for module, item in modules.items():
        owner_roots = [
            binding["path"]
            for binding in registered.get(module, {}).get("rootBindings", [])
        ]
        findings.require(
            bool(owner_roots) and item.get("sourceRoot") in owner_roots,
            "canonical_owner_root",
            f"{module} source root is not registered to its canonical owner",
        )
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
            name = operation["operation"]
            if not name.strip() or name in operations:
                findings.add(
                    "duplicate_or_empty_operation",
                    f"{module} has an invalid operation identity: {name!r}",
                )
                continue
            operations[name] = operation
        findings.require(
            bool(operations),
            "operations_missing",
            f"{module} has no registered source operations",
        )
        canonical_operations = operation_registry.get(module, {})
        findings.require(
            set(operations) == set(canonical_operations),
            "operation_closed_world",
            f"{module} operation set differs from the registered Lane E subset",
        )
        for operation_name, operation in operations.items():
            source_path = relative_path(
                operation.get("source"), findings, f"{module}.{operation_name}.source"
            )
            source_name = operation.get("source")
            source_owners = {
                owner
                for owner, row in registered.items()
                for binding in row.get("rootBindings", [])
                if isinstance(source_name, str)
                and (
                    source_name == binding["path"]
                    or source_name.startswith(binding["path"] + "/")
                )
            }
            findings.require(
                source_owners == {module},
                "canonical_operation_owner",
                f"{module}.{operation_name} has an unknown, foreign or ambiguous "
                "source owner",
            )
            canonical = canonical_operations.get(operation_name)
            findings.require(
                canonical is not None
                and all(
                    operation.get(key) == canonical.get(key)
                    for key in ("source", "nativeSymbol")
                ),
                "canonical_operation_binding",
                f"{module}.{operation_name} differs from its registered "
                "source/symbol binding",
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
            text = rust_code(path.read_text(encoding="utf-8"))
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
        {case.get("module") for case in cases.values()} == set(modules),
        "case_module_coverage",
        "registered modules must each retain native behavioral traceability",
    )
    case_registry = registered_cases(findings)
    findings.require(
        set(cases) == set(case_registry),
        "case_closed_world",
        "traceability cases must match the canonical module dossiers",
    )

    source_cache: dict[Path, str] = {}
    for case_id, case in cases.items():
        module = case.get("module")
        findings.require(
            module in modules,
            "case_module",
            f"{case_id} has invalid module {module!r}",
        )
        findings.require(
            case_registry.get(case_id) == module,
            "canonical_case_owner",
            f"{case_id} does not belong to its canonical dossier module",
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
            if source_path not in source_cache:
                source_cache[source_path] = rust_code(
                    source_path.read_text(encoding="utf-8")
                )
            source_text = source_cache[source_path]
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
        isinstance(cross_raw, list) and bool(cross_raw),
        "cross_case_count",
        "at least one Lane E cross-crate case is required",
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
                text = rust_code(source_path.read_text(encoding="utf-8"))
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
        isinstance(boundary_raw, list) and bool(boundary_raw),
        "product_boundary_case_count",
        "at least one product-boundary case is required",
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
                text = rust_code(source_path.read_text(encoding="utf-8"))
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

    for source, label in (
        (lib, "crate root"),
        (closure, "closure"),
        (metric, "metric roles"),
    ):
        exposed = unsigned_root_exports(source)
        findings.require(
            not exposed,
            "learning_eval_unsigned_public",
            f"{label} exposes unsigned default decision entrypoints: {sorted(exposed)}",
        )
    for token in (
        "trusted-inprocess-eval = []",
        "pub mod trusted_inprocess",
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


def rust_code(text: str) -> str:
    """Mask Rust comments/literals without changing source offsets."""
    code = list(text)
    index = 0
    raw_literal = re.compile(r'(?:br|cr|r)(#*)"')
    char_literal = re.compile(
        r"'(?:\\(?:x[0-9a-fA-F]{2}|u\{[0-9a-fA-F_]+\}|.)|[^'\\\n])'"
    )
    while index < len(text):
        end = index
        if text.startswith("//", index):
            end = text.find("\n", index)
            if end < 0:
                end = len(text)
        elif text.startswith("/*", index):
            depth = 1
            end = index + 2
            while end < len(text) and depth:
                if text.startswith("/*", end):
                    depth += 1
                    end += 2
                elif text.startswith("*/", end):
                    depth -= 1
                    end += 2
                else:
                    end += 1
        else:
            raw = raw_literal.match(text, index)
            if raw and (index == 0 or not text[index - 1].isalnum()):
                closing = '"' + raw[1]
                stop = text.find(closing, raw.end())
                end = len(text) if stop < 0 else stop + len(closing)
            elif text[index] == '"':
                end = index + 1
                while end < len(text):
                    if text[end] == "\\":
                        end += 2
                    elif text[end] == '"':
                        end += 1
                        break
                    else:
                        end += 1
            elif text[index] == "'":
                char = char_literal.match(text, index)
                if char:
                    end = char.end()
        if end > index:
            for offset in range(index, min(end, len(code))):
                if code[offset] != "\n":
                    code[offset] = " "
            index = end
        else:
            index += 1
    return "".join(code)


def without_qualification_items(text: str, feature: str) -> str:
    """Remove only items carrying the exact, independently checked feature gate.

    An any()/cfg_attr()/unknown gate is not an exemption. Item bodies are
    balanced on masked code, so braces in comments and literals cannot enlarge
    the excluded region or hide a following product writer.
    """
    code = rust_code(text)
    output = list(text)
    gate = re.compile(
        r'#\[\s*cfg\s*\(\s*feature\s*=\s*"' + re.escape(feature) + r'"\s*\)\s*\]'
    )
    for match in gate.finditer(text):
        if code[match.start()] != "#":
            continue
        start = match.end()
        while True:
            attributes = re.match(r"\s*#\[[^\]]*\]", code[start:])
            if not attributes:
                break
            start += attributes.end()
        item = re.match(
            r"\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:fn|use)\b", code[start:]
        )
        if not item:
            continue
        cursor = start + item.end()
        brackets: list[str] = []
        body = False
        complete = False
        while cursor < len(code):
            char = code[cursor]
            if char in "([{":
                if char == "{" and not brackets:
                    body = True
                brackets.append(char)
            elif char in ")]}":
                if not brackets or {"(": ")", "[": "]", "{": "}"}[brackets[-1]] != char:
                    break
                brackets.pop()
                if body and not brackets:
                    cursor += 1
                    complete = True
                    break
            elif char == ";" and not brackets:
                cursor += 1
                complete = True
                break
            cursor += 1
        else:
            continue
        if brackets or not complete:
            continue
        for offset in range(match.start(), cursor):
            if output[offset] != "\n":
                output[offset] = " "
    return "".join(output)


def feature_is_explicit(manifest: dict[str, Any], feature: str) -> bool:
    features = manifest.get("features", {})
    if (
        not isinstance(features, dict)
        or feature not in features
        or not all(
            isinstance(members, list)
            and all(isinstance(member, str) for member in members)
            for members in features.values()
        )
    ):
        return False
    pending = list(features.get("default", []))
    seen: set[str] = set()
    while pending:
        name = pending.pop()
        if not isinstance(name, str) or name == feature:
            return False
        if name not in seen:
            seen.add(name)
            pending.extend(features.get(name, []))
    return True


def legacy_writer_uses(
    text: str,
    *,
    qualification_feature: str | None = None,
    read_only_journal: bool = False,
) -> list[str]:
    if qualification_feature is not None:
        text = without_qualification_items(text, qualification_feature)
    code = rust_code(text)
    # A narrow read-only match arm extracts an existing record's identity. Any
    # constructor, mutable arm, alternative expression or raw append still fails.
    code = re.sub(
        r"\bLedgerEvent\s*::\s*(Decision|Outcome|Credit|Revocation)\s*\(\s*([A-Za-z_]\w*)\s*\)\s*=>\s*&\s*\2\s*\.\s*record_id\s*(?=,|})",
        "",
        code,
    )
    if read_only_journal:
        code = re.sub(
            r"\buse\s+codex_hepta_learning_ledger\s*::\s*DurableLearningJournal\s*;",
            "",
            code,
        )
    forbidden = {
        r"\bDurableLearningJournal\b": "unresolved legacy durable journal use",
        r"\bLedgerEvent\s*::\s*Decision\b": "raw V1 Decision construction or unresolved use",
        r"\bLedgerEvent\s*::\s*Outcome\b": "raw V1 Outcome construction or unresolved use",
        r"\bLedgerEvent\s*::\s*Credit\b": "raw V1 Credit construction or unresolved use",
        r"\bLedgerEvent\s*::\s*Revocation\b": "raw V1 Revocation construction or unresolved use",
        r"\bLedgerEvent\s*(?:as\b|::\s*[\{*])": "ambiguous legacy event alias/import",
        r"\btype\s+\w+\s*=\s*(?:\w+\s*::\s*)*LedgerEvent\b": "ambiguous legacy event type alias",
        r"\.\s*append_qualification\s*\(": "qualification append in the product surface",
    }
    if read_only_journal and re.search(r"\bDurableLearningJournal\b", rust_code(text)):
        forbidden[r"\.\s*append_decision\s*\("] = (
            "ambiguous legacy journal Decision append"
        )
    return [
        description
        for pattern, description in forbidden.items()
        if re.search(pattern, code)
    ]


def verify_product_writer_exclusivity(findings: Findings) -> None:
    """Prevent product crates from bypassing LedgerWriter with raw V1 appends."""

    allowed_roots = {
        "codex-rs/hepta-learning-ledger",
        "codex-rs/hepta-shadow-qualification",
    }
    agent_feature = "qualification-legacy-learning-write"
    ledger_feature = "qualification-legacy-write"
    try:
        agent_manifest = tomllib.loads(
            (ROOT / "codex-rs/hepta-agentd/Cargo.toml").read_text()
        )
        ledger_manifest = tomllib.loads(
            (ROOT / "codex-rs/hepta-learning-ledger/Cargo.toml").read_text()
        )
        qualification_only = (
            feature_is_explicit(agent_manifest, agent_feature)
            and feature_is_explicit(ledger_manifest, ledger_feature)
            and agent_manifest["features"][agent_feature]
            == ["codex-hepta-learning-ledger/" + ledger_feature]
        )
        journal = (ROOT / "codex-rs/hepta-learning-ledger/src/journal.rs").read_text()
        journal = rust_code(without_qualification_items(journal, ledger_feature))
        trait = re.search(
            r"pub\s+trait\s+DurableLearningJournal\s*:\s*sealed\s*::\s*Journal\s*\{([^{}]*)\}",
            journal,
        )
        read_only_journal = bool(
            qualification_only
            and trait
            and set(re.findall(r"\bfn\s+(\w+)\s*\(", trait[1]))
            == {"snapshot", "anchor"}
        )
    except (OSError, ValueError, KeyError):
        qualification_only = read_only_journal = False

    for path in (ROOT / "codex-rs").rglob("*.rs"):
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
        if not any(
            token in text
            for token in (
                "LedgerEvent",
                "DurableLearningJournal",
                "append_qualification",
            )
        ):
            continue
        feature = (
            agent_feature
            if qualification_only and relative.startswith("codex-rs/hepta-agentd/")
            else None
        )
        for description in legacy_writer_uses(
            text, qualification_feature=feature, read_only_journal=read_only_journal
        ):
            findings.add(
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
