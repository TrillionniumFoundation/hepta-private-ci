#!/usr/bin/env python3
"""Validate the canonical control.runtime maturity facts without mutating them."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "docs/modules/control.runtime/CURRENT_STATE.json"
IMPLEMENTATION_MAP = ROOT / "docs/modules/control.runtime/IMPLEMENTATION_MAP.json"

STAGES = [
    "designDefined",
    "sourcePresent",
    "guardedPublicEntry",
    "productCallsiteIntegrated",
    "exactSourceTestsPassed",
    "fixedMergeCandidatePassed",
    "targetHostRecoveryPassed",
    "independentlyAccepted",
    "activated",
    "released",
]

REQUIRED_OPERATIONS = {
    "collect_snapshot",
    "prepare_plan",
    "bind_ndu_plan_evaluation_v1",
    "finalize_plan",
    "request_execution_grants",
    "plan_authenticated_observed_context",
    "PlannerJournalV1",
    "PlannerStoreV1",
    "execute_planner_request_v1",
    "reconcile_planner_request_v1",
    "OrganHostV1::dispatch_once_with_receipt",
}

DOCUMENT_PATH_FIELDS = (
    "canonicalStatusSource",
    "technicalGuide",
    "executionSpecification",
    "convergenceGuide",
)


def load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected object")
    return value


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def repository_path(value: Any, field: str) -> Path:
    require(isinstance(value, str) and value, f"{field}: expected non-empty path")
    path = ROOT / value
    require(path.is_file(), f"{field}: missing file {value}")
    return path


def validate() -> dict[str, Any]:
    state = load(STATE)
    implementation = load(IMPLEMENTATION_MAP)

    require(
        state.get("schema") == "hepta.module-current-state.v2",
        "unexpected state schema",
    )
    require(state.get("module") == "control.runtime", "state module mismatch")
    require(state.get("canonicalStatusSource") is True, "state must be canonical")
    require(
        state.get("authorityDelta") == "none",
        "control.runtime cannot claim authority",
    )
    require(state.get("stageOrder") == STAGES, "stage order drift")

    subsystems = state.get("subsystems")
    require(
        isinstance(subsystems, dict) and subsystems,
        "subsystems must be non-empty",
    )
    for name, subsystem in subsystems.items():
        require(isinstance(subsystem, dict), f"{name}: expected object")
        for stage in STAGES:
            require(
                type(subsystem.get(stage)) is bool,
                f"{name}.{stage}: expected boolean",
            )
        require(
            not subsystem["guardedPublicEntry"] or subsystem["sourcePresent"],
            f"{name}: guarded entry requires source",
        )
        require(
            not subsystem["productCallsiteIntegrated"]
            or subsystem["guardedPublicEntry"],
            f"{name}: product callsite requires guarded entry",
        )
        require(
            not subsystem["fixedMergeCandidatePassed"]
            or subsystem["exactSourceTestsPassed"],
            f"{name}: fixed merge cannot precede exact source tests",
        )
        require(
            not subsystem["targetHostRecoveryPassed"]
            or subsystem["productCallsiteIntegrated"],
            f"{name}: target-host recovery requires a product callsite",
        )
        require(
            not subsystem["activated"] or subsystem["independentlyAccepted"],
            f"{name}: activation requires independent acceptance",
        )
        require(
            not subsystem["released"] or subsystem["activated"],
            f"{name}: release requires activation",
        )
        notes = subsystem.get("notes")
        require(
            isinstance(notes, list)
            and notes
            and all(isinstance(note, str) and note for note in notes),
            f"{name}.notes: expected non-empty strings",
        )

    gates = state.get("externalEvidenceGates")
    require(
        isinstance(gates, dict) and gates,
        "externalEvidenceGates must be non-empty",
    )
    require(
        all(value is False for value in gates.values()),
        "external gates cannot be self-certified",
    )

    require(
        implementation.get("module") == "control.runtime",
        "implementation map module mismatch",
    )
    require(
        implementation.get("authorityDelta") == "none",
        "implementation map authority drift",
    )
    require(
        implementation.get("canonicalStatusSource")
        == "docs/modules/control.runtime/CURRENT_STATE.json",
        "implementation map must point to the canonical current state",
    )
    require(
        implementation.get("productionImplementation") is False,
        "source map cannot assert production",
    )

    verified_documents: list[str] = []
    for field in DOCUMENT_PATH_FIELDS:
        path = repository_path(implementation.get(field), field)
        verified_documents.append(str(path.relative_to(ROOT)))

    source_roots = implementation.get("sourceRoot")
    require(
        isinstance(source_roots, list) and source_roots,
        "sourceRoot must be a non-empty list",
    )
    for value in source_roots:
        require(
            isinstance(value, str) and (ROOT / value).is_dir(),
            f"missing source root: {value}",
        )

    claim = implementation.get("claimBoundary", {})
    require(isinstance(claim, dict), "claimBoundary must be an object")
    for key in (
        "productExecutionProved",
        "targetHostRecoveryProved",
        "independentAcceptance",
        "activation",
        "release",
    ):
        require(
            claim.get(key) is False,
            f"implementation map prematurely asserts {key}",
        )

    operations = implementation.get("operations", [])
    require(isinstance(operations, list), "implementation operations must be a list")
    operation_names = {
        operation.get("operation")
        for operation in operations
        if isinstance(operation, dict)
    }
    missing_operations = sorted(REQUIRED_OPERATIONS - operation_names)
    require(
        not missing_operations,
        f"missing hardened operations: {missing_operations}",
    )

    verified_test_bindings = 0
    source_cache: dict[Path, str] = {}
    for operation in operations:
        require(
            isinstance(operation, dict),
            "implementation operation must be an object",
        )
        operation_name = operation.get("operation")
        require(
            isinstance(operation_name, str) and operation_name,
            "implementation operation requires a name",
        )
        source_path = repository_path(
            operation.get("sourcePath"),
            f"{operation_name}.sourcePath",
        )
        require(
            operation.get("sourcePathExists") is True,
            f"{operation_name}.sourcePathExists must remain true",
        )
        require(
            isinstance(operation.get("nativeSymbol"), str)
            and operation["nativeSymbol"],
            f"{operation_name}.nativeSymbol: expected non-empty string",
        )

        tests = operation.get("tests")
        require(
            isinstance(tests, list) and tests,
            f"{operation_name}.tests: at least one exact test binding is required",
        )
        for index, test in enumerate(tests):
            require(
                isinstance(test, dict),
                f"{operation_name}.tests[{index}]: expected object",
            )
            test_path = repository_path(
                test.get("path"),
                f"{operation_name}.tests[{index}].path",
            )
            symbol = test.get("symbol")
            require(
                isinstance(symbol, str) and symbol,
                f"{operation_name}.tests[{index}].symbol: expected non-empty string",
            )
            source_text = source_cache.get(test_path)
            if source_text is None:
                source_text = test_path.read_text(encoding="utf-8")
                source_cache[test_path] = source_text
            require(
                symbol in source_text,
                f"{operation_name}.tests[{index}]: symbol {symbol!r} "
                f"not found in {test_path.relative_to(ROOT)}",
            )
            verified_test_bindings += 1

        # Reading the source here also guarantees it is UTF-8 and not merely a
        # path-shaped placeholder.
        source_cache.setdefault(source_path, source_path.read_text(encoding="utf-8"))

    return {
        "schema": "hepta.control-runtime-state-validation.v2",
        "module": state["module"],
        "subsystems": sorted(subsystems),
        "stages": STAGES,
        "external_gates_remain_false": True,
        "implementation_operations": len(operations),
        "required_operations_present": sorted(REQUIRED_OPERATIONS),
        "verified_documents": verified_documents,
        "verified_test_bindings": verified_test_bindings,
        "result": "pass",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = validate()
    except (OSError, ValueError, json.JSONDecodeError, UnicodeError) as error:
        result = {
            "schema": "hepta.control-runtime-state-validation.v2",
            "result": "fail",
            "error": str(error),
        }
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(result, indent=2) + "\n",
                encoding="utf-8",
            )
        print(json.dumps(result, indent=2))
        return 1

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
