#!/usr/bin/env python3
"""Semantic closed-world validation for the Lane G implementation."""
from __future__ import annotations

import ast
from dataclasses import MISSING, fields, is_dataclass
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = ROOT / "tools/hepta-engineering-control"
IMPLEMENTATION_ROOT = PACKAGE_ROOT / "control_engineering_v2"
COMPONENTS = IMPLEMENTATION_ROOT / "COMPONENTS.json"
TRACEABILITY = IMPLEMENTATION_ROOT / "TRACEABILITY.json"
TEST_FILE = PACKAGE_ROOT / "test_control_engineering_v2.py"
EXPECTED_COMPONENTS = {
    "canonical-repository-path",
    "work-envelope-store",
    "path-lease-arbiter",
    "assignment-scheduler",
    "audit-projection",
    "integration-decision-store",
    "integration-evidence-verifier",
    "candidate-generator",
    "candidate-sandbox",
    "independent-review-adapter",
    "assimilation-manifest-and-contracts",
    "assimilation-qualification-adapter",
    "public-composition-facade",
}
EXPECTED_OPERATIONS = {
    "issue_work_envelope",
    "schedule_ready_packages",
    "acquire_path_lease",
    "generate_candidate",
    "execute_candidate_sandbox",
    "verify_integration_evidence",
    "request_independent_review",
    "record_integration_decision",
    "publish_audit_projection",
    "prepare_assimilation_candidate",
}
AUTHORITY_KEYS = {
    "runtimeAuthority",
    "mergeAuthority",
    "activationAuthority",
    "promotionAuthority",
    "releaseAuthority",
    "externalEffectAuthority",
    "independentAcceptance",
    "canonicalSelection",
}
EXTERNAL_GATES = {f"RDY-EXT-{number:03d}" for number in range(1, 10)}
FORBIDDEN_PUBLIC_NAMES = {
    "merge_pull_request",
    "select_candidate",
    "activate_candidate",
    "promote_candidate",
    "release_candidate",
    "enroll_peer",
    "copy_credential",
}


class ValidationError(ValueError):
    pass


def fail(code: str) -> None:
    raise ValidationError(code)


def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        fail("invalid_json:" + path.as_posix())
    if not isinstance(value, dict):
        fail("invalid_json_root:" + path.as_posix())
    return value


def parse_source(path: Path) -> ast.Module:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeError, SyntaxError):
        fail("invalid_python:" + path.as_posix())


def source_symbols(tree: ast.Module) -> set[str]:
    symbols: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.add(node.name)
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbols.add(node.name + "." + child.name)
    return symbols


def test_symbols(path: Path) -> set[str]:
    tree = parse_source(path)
    result: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    result.add(node.name + "." + child.name)
    return result


def verify_subprocess_safety(tree: ast.Module, label: str) -> None:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg == "shell" and isinstance(keyword.value, ast.Constant):
                if keyword.value.value is True:
                    fail("shell_true:" + label)


def verify_authority_defaults(implementation: object) -> None:
    names = (
        "LeaseReceipt",
        "ScheduleReceipt",
        "EvidenceDecision",
        "Candidate",
        "SandboxReceipt",
        "AssimilationProposal",
        "ReviewRequest",
    )
    for name in names:
        value = getattr(implementation, name, None)
        if value is None or not is_dataclass(value):
            fail("receipt_dataclass:" + name)
        for field in fields(value):
            lowered = field.name.lower()
            if any(token in lowered for token in ("authority", "acceptance", "activation", "promotion", "release", "propagation", "federation")):
                if field.default is MISSING or field.default is not False:
                    fail("positive_or_required_authority_field:" + name + ":" + field.name)


def verify() -> dict[str, object]:
    components = load_json(COMPONENTS)
    traceability = load_json(TRACEABILITY)
    if components.get("schema") != "hepta.control-engineering-components.v2":
        fail("component_schema")
    if traceability.get("schema") != "hepta.control-engineering-traceability.v2":
        fail("traceability_schema")
    if components.get("module") != "control.engineering" or traceability.get("module") != "control.engineering":
        fail("module_identity")
    authority = components.get("authorityFlags")
    if not isinstance(authority, dict) or set(authority) != AUTHORITY_KEYS:
        fail("authority_key_closure")
    if any(value is not False for value in authority.values()):
        fail("positive_authority")
    external = components.get("externalGates")
    if not isinstance(external, dict) or set(external) != EXTERNAL_GATES:
        fail("external_gate_closure")
    if any(value != "open_external" for value in external.values()):
        fail("external_gate_fabricated")

    parsed: dict[Path, ast.Module] = {}
    symbols: dict[Path, set[str]] = {}
    component_rows = components.get("components")
    if not isinstance(component_rows, list):
        fail("component_rows")
    by_id: dict[str, dict] = {}
    for row in component_rows:
        if not isinstance(row, dict):
            fail("component_shape")
        identity = row.get("id")
        if not isinstance(identity, str) or not identity or identity in by_id:
            fail("component_identity")
        by_id[identity] = row
        if row.get("state") != "source_implemented":
            fail("component_state:" + identity)
        for key in ("source", "symbols", "failureModel", "resourceBounds", "rollback"):
            if key not in row:
                fail("component_field:" + identity + ":" + key)
        source = ROOT / str(row["source"])
        try:
            source.resolve().relative_to(IMPLEMENTATION_ROOT.resolve())
        except ValueError:
            fail("component_source_scope:" + identity)
        if source not in parsed:
            parsed[source] = parse_source(source)
            symbols[source] = source_symbols(parsed[source])
            verify_subprocess_safety(parsed[source], source.name)
        required_symbols = row["symbols"]
        if not isinstance(required_symbols, list) or not required_symbols:
            fail("component_symbols:" + identity)
        missing = set(required_symbols) - symbols[source]
        if missing:
            fail("missing_native_symbol:" + identity + ":" + sorted(missing)[0])
        if not isinstance(row["failureModel"], list) or not row["failureModel"]:
            fail("failure_model:" + identity)
        if not isinstance(row["resourceBounds"], dict) or not row["resourceBounds"]:
            fail("resource_bounds:" + identity)
        if not isinstance(row["rollback"], str) or not row["rollback"]:
            fail("rollback:" + identity)
    if set(by_id) != EXPECTED_COMPONENTS:
        fail("component_closed_set")

    available_tests = test_symbols(TEST_FILE)
    operation_rows = traceability.get("operations")
    if not isinstance(operation_rows, list):
        fail("operation_rows")
    operations: dict[str, dict] = {}
    for row in operation_rows:
        if not isinstance(row, dict):
            fail("operation_shape")
        identity = row.get("designOperation")
        if not isinstance(identity, str) or not identity or identity in operations:
            fail("operation_identity")
        operations[identity] = row
        if row.get("state") != "source_implemented":
            fail("operation_state:" + identity)
        native_module = row.get("nativeModule")
        if not isinstance(native_module, str) or not native_module.startswith("control_engineering_v2."):
            fail("native_module:" + identity)
        relative = native_module.removeprefix("control_engineering_v2.").replace(".", "/") + ".py"
        module_path = IMPLEMENTATION_ROOT / relative
        if module_path not in parsed:
            parsed[module_path] = parse_source(module_path)
            symbols[module_path] = source_symbols(parsed[module_path])
            verify_subprocess_safety(parsed[module_path], module_path.name)
        if row.get("nativeSymbol") not in symbols[module_path]:
            fail("operation_native_symbol:" + identity)
        tests = row.get("tests")
        if not isinstance(tests, list) or not tests or not set(tests).issubset(available_tests):
            fail("operation_tests:" + identity)
        if not isinstance(row.get("capabilityCeiling"), str) or not row["capabilityCeiling"]:
            fail("operation_ceiling:" + identity)
    if set(operations) != EXPECTED_OPERATIONS:
        fail("operation_closed_set")

    sys.path.insert(0, str(PACKAGE_ROOT))
    try:
        import control_engineering_v2 as implementation
    except Exception as error:
        fail("implementation_import:" + type(error).__name__)
    for operation in EXPECTED_OPERATIONS - {"acquire_path_lease"}:
        if not callable(getattr(implementation, operation, None)):
            fail("public_export:" + operation)
    if not callable(getattr(implementation.EngineeringStore, "acquire_path_lease", None)):
        fail("public_export:acquire_path_lease")
    if FORBIDDEN_PUBLIC_NAMES & set(getattr(implementation, "__all__", ())):
        fail("forbidden_public_capability")
    verify_authority_defaults(implementation)

    return {
        "status": "PASS_LANE_G_SEMANTIC_CLOSED_WORLD",
        "components": len(by_id),
        "operations": len(operations),
        "tests": len(available_tests),
        "authorityGranted": False,
        "externalGatesPassed": False,
    }


def main() -> int:
    try:
        result = verify()
    except ValidationError as error:
        print(
            json.dumps(
                {
                    "status": "FAIL_LANE_G_SEMANTIC_CLOSED_WORLD",
                    "error": str(error),
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
