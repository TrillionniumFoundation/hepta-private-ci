#!/usr/bin/env python3
"""Validate the fail-closed Lane G hardening layer and its CI identity."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import sys


EXPECTED_CONTROLS = {
    "G-HARD-001",
    "G-HARD-002",
    "G-HARD-003",
    "G-HARD-004",
    "G-HARD-005",
    "G-HARD-006",
}
EXPECTED_SYMBOLS = {
    "_engineering_error_init",
    "_run_immediate",
    "_hardened_schedule",
    "assignment_frontier",
    "hardened_sandbox_candidate",
    "hardened_execute_candidate_sandbox",
    "CandidateEvidenceBindingReceipt",
    "BoundEvidenceDecision",
    "bind_candidate_evidence",
    "hardened_request_independent_review",
    "hardened_record_integration_decision",
    "OwnerConsentAttestation",
    "SandboxParityAttestation",
    "AttestedSandboxParity",
    "hardened_prepare_assimilation_candidate",
    "install_hardening",
}
PUBLIC_REBINDINGS = {
    "sandbox_candidate = hardened_sandbox_candidate",
    "execute_candidate_sandbox = hardened_execute_candidate_sandbox",
    "request_independent_review = hardened_request_independent_review",
    "record_integration_decision = hardened_record_integration_decision",
    "prepare_assimilation_candidate = hardened_prepare_assimilation_candidate",
}
WORKFLOW_TOKENS = {
    "source-head",
    "synthetic-merge",
    "github.event.pull_request.head.sha",
    "merge-tree --write-tree",
    "test_lane_g_hardening.py",
    "lane_g_hardening_validate.py",
    "hepta-module-docs.py verify",
    "hepta-readiness.py verify",
    "hepta-docs.py verify",
    "hepta-technical-closure.py verify",
    "hepta-repository-integrity.py self-test",
}
FORBIDDEN_SOURCE_DEFINITIONS = {
    "merge_candidate",
    "self_merge",
    "activate_candidate",
    "promote_candidate",
    "release_candidate",
    "deploy_candidate",
    "enroll_peer",
    "propagate_credentials",
}


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AssertionError(f"invalid JSON {path}: {error}") from error


def source_symbols(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError) as error:
        raise AssertionError(f"invalid Python {path}: {error}") from error
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }


def verify() -> dict[str, object]:
    root = project_root()
    package = root / "tools/hepta-engineering-control/control_engineering_v2"
    registry_path = package / "HARDENING.json"
    maturity_path = package / "MATURITY.json"
    hardening_path = package / "hardening.py"
    tests_path = root / "tools/hepta-engineering-control/test_lane_g_hardening.py"
    exports_path = package / "__init__.py"
    workflow_path = root / ".github/workflows/hepta-lane-g-engineering.yml"
    integrity_path = root / "scripts/hepta-repository-integrity.py"
    retired_path = root / ".github/workflows/hepta-gap-closure.yml"

    for path in (
        registry_path,
        maturity_path,
        package / "HARDENING.md",
        hardening_path,
        tests_path,
        exports_path,
        workflow_path,
        integrity_path,
    ):
        if not path.is_file():
            raise AssertionError(f"missing required Lane G hardening artifact: {path}")
    if retired_path.exists():
        raise AssertionError("retired self-materializing workflow remains executable")

    registry = load_json(registry_path)
    if not isinstance(registry, dict):
        raise AssertionError("hardening registry must be an object")
    if registry.get("schema") != "hepta.control.engineering.hardening.v1":
        raise AssertionError("hardening schema drift")
    if registry.get("moduleId") != "control.engineering":
        raise AssertionError("hardening module drift")
    controls = registry.get("controls")
    if not isinstance(controls, list):
        raise AssertionError("hardening controls must be a list")
    control_ids = {
        item.get("id")
        for item in controls
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    if control_ids != EXPECTED_CONTROLS:
        raise AssertionError(
            f"hardening control closure mismatch: expected={sorted(EXPECTED_CONTROLS)} "
            f"actual={sorted(control_ids)}"
        )

    symbols = source_symbols(hardening_path)
    missing_symbols = EXPECTED_SYMBOLS - symbols
    if missing_symbols:
        raise AssertionError(f"missing hardening symbols: {sorted(missing_symbols)}")
    forbidden = FORBIDDEN_SOURCE_DEFINITIONS & symbols
    if forbidden:
        raise AssertionError(f"forbidden authority symbol implemented: {sorted(forbidden)}")

    tests = tests_path.read_text(encoding="utf-8")
    declared_tests = {
        test
        for control in controls
        if isinstance(control, dict)
        for test in control.get("tests", [])
        if isinstance(test, str) and test.startswith("test_")
    }
    missing_tests = sorted(test for test in declared_tests if f"def {test}(" not in tests)
    if missing_tests:
        raise AssertionError(f"declared hardening tests missing: {missing_tests}")

    exports = exports_path.read_text(encoding="utf-8")
    missing_rebindings = sorted(token for token in PUBLIC_REBINDINGS if token not in exports)
    if missing_rebindings:
        raise AssertionError(f"public hardening rebindings missing: {missing_rebindings}")

    workflow = workflow_path.read_text(encoding="utf-8")
    missing_workflow = sorted(token for token in WORKFLOW_TOKENS if token not in workflow)
    if missing_workflow:
        raise AssertionError(f"Lane G workflow identity incomplete: {missing_workflow}")
    for denied in ("persist-credentials: true", "git push", "contents: write"):
        if denied in workflow:
            raise AssertionError(f"Lane G workflow contains forbidden capability: {denied}")

    integrity = integrity_path.read_text(encoding="utf-8")
    if "--diff-filter=ACMRTD" not in integrity:
        raise AssertionError("repository integrity does not include deletions")
    if "PROTECTED_DELETION" not in integrity:
        raise AssertionError("repository integrity lacks protected-deletion policy")

    maturity = load_json(maturity_path)
    if not isinstance(maturity, dict):
        raise AssertionError("maturity registry must be an object")
    expected_maturity = {
        "documentationStatus": "semantically_complete_for_repository_owned_scope",
        "sourceStatus": "hardened_candidate",
        "implementationStatus": "bounded_source_complete",
        "stateBindingStatus": "persistent_with_schema_version_and_frontier_binding",
        "qualificationStatus": "exact_head_and_synthetic_merge_required",
        "activationStatus": "dormant",
        "authorityStatus": "none",
    }
    for key, expected in expected_maturity.items():
        if maturity.get(key) != expected:
            raise AssertionError(
                f"maturity drift for {key}: expected={expected!r} actual={maturity.get(key)!r}"
            )
    external = maturity.get("externalGates")
    if not isinstance(external, dict) or external.get("status") != "open_external":
        raise AssertionError("external gates must remain explicitly open_external")
    if external.get("mayBeSelfAsserted") is not False:
        raise AssertionError("external gates may not be self asserted")

    return {
        "schema": "hepta.control.engineering.hardening.validation.v1",
        "moduleId": "control.engineering",
        "controlCount": len(control_ids),
        "symbolCount": len(EXPECTED_SYMBOLS),
        "testCount": len(declared_tests),
        "sourceIdentityRequired": True,
        "syntheticMergeIdentityRequired": True,
        "activation": False,
        "mergeAuthority": False,
        "releaseAuthority": False,
        "externalGates": "open_external",
    }


def main(argv: list[str]) -> int:
    if argv not in (["verify"], ["self-test"]):
        print("usage: lane_g_hardening_validate.py verify|self-test", file=sys.stderr)
        return 2
    try:
        report = verify()
    except AssertionError as error:
        print(json.dumps({"status": "failed", "error": str(error)}, sort_keys=True))
        return 1
    print(json.dumps({"status": "ok", **report}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
