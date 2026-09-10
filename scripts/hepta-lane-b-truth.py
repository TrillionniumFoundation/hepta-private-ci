#!/usr/bin/env python3
"""Fail-closed validator for the Lane B implementation truth boundary."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TRUTH_PATH = ROOT / "qualification/lane-b/LANE_B_IMPLEMENTATION_TRUTH.json"
READINESS_PATH = ROOT / "docs/readiness/READINESS.json"
SOURCE_BINDINGS_PATH = ROOT / "docs/modules/SOURCE_BINDINGS.json"
NATIVE_BINDINGS_PATH = ROOT / "qualification/module-execution-dossiers/NATIVE_BINDINGS.json"

EXPECTED_MODULES = [
    "runtime.supervisor",
    "runtime.fleet",
    "runtime.agentd",
    "runtime.codex",
    "inference.control",
    "inference.worker",
    "automation.taskflow",
    "channel.matrix",
    "browser.servo",
    "ui.control",
    "ui.native",
]
EXPECTED_OPERATIONS = {
    "runtime.supervisor": ["start_instance", "observe_health", "drain", "load_next"],
    "runtime.fleet": ["admit_host", "allocate", "renew_or_revoke"],
    "runtime.agentd": ["compose_runtime", "start_run", "cancel_run", "attach_context"],
    "runtime.codex": ["open_thread", "submit_turn", "dispatch_tool", "observe_delivery"],
    "inference.control": ["reserve_request", "schedule", "cancel", "settle"],
    "inference.worker": ["load_model", "run", "unload"],
    "automation.taskflow": [
        "register_schedule",
        "materialize_due",
        "claim_occurrence",
        "execute_step",
    ],
    "channel.matrix": ["admit_event", "prepare_send", "observe_send"],
    "browser.servo": ["open_profile", "observe_page", "navigate_or_act"],
    "ui.control": ["read_view", "submit_request", "request_stop"],
    "ui.native": [
        "connect_runtime",
        "render_runtime_view",
        "request_platform_capability",
        "apply_shell_update",
    ],
}
EXPECTED_FALSE_CLAIMS = [
    "targetDesignImplementationClosed",
    "productionConsumerCallsitesProved",
    "productExecutionProved",
    "deploymentProved",
    "independentAcceptanceProved",
    "externalEffectsProved",
    "hardwareEvidenceProved",
    "futureWindowEfficacyProved",
]
EXPECTED_TRUE_RULES = [
    "rootMaterializationIsNotImplementation",
    "designOperationIsNotNativeSymbol",
    "libraryReachabilityIsNotProductionCallsite",
    "callerSuppliedObservationIsNotTerminalProof",
    "qualificationOnlyIsNotProduction",
    "oneSourceBlobIsNotModuleClosure",
    "externalEvidenceCannotBeSelfIssued",
]
ALLOWED_MATURITY = {
    "partial_runtime",
    "boundary_and_ledger",
    "boundary_scaffold",
    "qualification_runtime",
    "presentation_core",
}
ALLOWED_ROOT_STATE = {"materialized", "materialized_alias", "materialized_pin"}
NO_RUNTIME_MATURITY = {"boundary_scaffold", "presentation_core"}
ALLOWED_STATES = {
    "implemented",
    "implemented_partial",
    "boundary_only",
    "mapping_required",
    "planned",
}


class Invalid(ValueError):
    pass


def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise Invalid(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    except Exception as exc:
        raise Invalid(f"{path.relative_to(ROOT)}: {exc}") from exc


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Invalid(message)


def git(*args: str) -> str:
    process = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if process.returncode != 0:
        raise Invalid(
            f"git {' '.join(args)} failed: "
            f"{process.stderr.strip() or process.stdout.strip()}"
        )
    return process.stdout.strip()


def verify_baseline(truth: dict[str, Any]) -> None:
    baseline = truth["baseline"]
    commit = baseline["commit"]
    tree = baseline["tree"]
    require(
        len(commit) == 40 and all(ch in "0123456789abcdef" for ch in commit),
        "baseline commit shape",
    )
    require(
        len(tree) == 40 and all(ch in "0123456789abcdef" for ch in tree),
        "baseline tree shape",
    )
    require(git("rev-parse", f"{commit}^{{tree}}") == tree, "baseline tree mismatch")
    process = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
        cwd=ROOT,
        check=False,
    )
    require(process.returncode == 0, "baseline is not an ancestor of HEAD")


def lane_modules(readiness: dict[str, Any]) -> list[str]:
    rows = [
        row
        for row in readiness.get("implementationLanes", [])
        if row.get("id") == "LANE-B-RUNTIME"
    ]
    require(len(rows) == 1, "canonical Lane B row")
    modules = rows[0].get("modules")
    require(isinstance(modules, list), "canonical Lane B module list")
    return modules


def verify_native_anchor(module: str, native: dict[str, Any]) -> None:
    path = ROOT / native["path"]
    require(path.is_file(), f"{module} missing native anchor {native['path']}")
    text = path.read_text(encoding="utf-8")
    exports = native.get("exports")
    require(isinstance(exports, list) and exports, f"{module} native exports")
    for symbol in exports:
        require(
            isinstance(symbol, str) and symbol in text,
            f"{module} missing native export {symbol!r} in {native['path']}",
        )


def verify_operation(operation: dict[str, Any], module: str) -> None:
    require(
        list(operation)
        == ["designOperation", "state", "path", "symbol", "callerClass"],
        f"{module} operation shape",
    )
    op_id = operation["designOperation"]
    require(isinstance(op_id, str) and op_id, f"{module} operation id")
    state = operation["state"]
    require(state in ALLOWED_STATES, f"{module}/{op_id} operation state {state}")
    require(
        isinstance(operation["callerClass"], str) and operation["callerClass"],
        f"{module}/{op_id} caller class",
    )
    if state in {"planned", "mapping_required"}:
        require(
            operation["path"] is None and operation["symbol"] is None,
            f"{module}/{op_id} unresolved operation must not invent a mapping",
        )
        return
    require(
        isinstance(operation["path"], str)
        and isinstance(operation["symbol"], str),
        f"{module}/{op_id} mapped operation fields",
    )
    path = ROOT / operation["path"]
    require(path.is_file(), f"{module}/{op_id} missing path {operation['path']}")
    require(
        operation["symbol"] in path.read_text(encoding="utf-8"),
        f"{module}/{op_id} missing symbol {operation['symbol']!r}",
    )


def verify() -> int:
    truth = load(TRUTH_PATH)
    readiness = load(READINESS_PATH)
    source_bindings = load(SOURCE_BINDINGS_PATH)
    native_bindings = load(NATIVE_BINDINGS_PATH)

    require(
        truth.get("schema") == "hepta.lane-b-implementation-truth.v1"
        and truth.get("schemaVersion") == 1,
        "truth schema",
    )
    require(
        truth.get("documentClass") == "repository_controlled_truth_boundary",
        "truth document class",
    )
    require(
        truth.get("planId") == "HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN"
        and truth.get("planVersion") == "8.0.0"
        and truth.get("laneId") == "LANE-B-RUNTIME",
        "truth plan/lane binding",
    )

    claims = truth.get("claimBoundary")
    require(isinstance(claims, dict), "claim boundary")
    for key in [
        "repositoryTruthModelClosed",
        "laneModuleSetClosed",
        "observedSourceAnchorsClosed",
    ]:
        require(claims.get(key) is True, f"missing repository closure {key}")
    for key in EXPECTED_FALSE_CLAIMS:
        require(claims.get(key) is False, f"unsupported positive claim {key}")

    rules = truth.get("rules")
    require(isinstance(rules, dict), "truth rules")
    for key in EXPECTED_TRUE_RULES:
        require(rules.get(key) is True, f"missing truth rule {key}")

    require(
        truth.get("allowedOperationStates") == [
            "implemented",
            "implemented_partial",
            "boundary_only",
            "mapping_required",
            "planned",
        ],
        "operation-state vocabulary/order",
    )
    require(lane_modules(readiness) == EXPECTED_MODULES, "canonical Lane B order")
    require(truth.get("moduleOrder") == EXPECTED_MODULES, "truth module order")

    modules = truth.get("modules")
    require(isinstance(modules, list), "truth modules")
    require(
        [row.get("module") for row in modules] == EXPECTED_MODULES,
        "truth module closed world",
    )

    source_map = {
        row["module"]: row for row in source_bindings.get("bindings", [])
    }
    native_map = {
        row["module"]: row for row in native_bindings.get("observations", [])
    }
    require(set(EXPECTED_MODULES) <= set(source_map), "source binding coverage")
    require(set(EXPECTED_MODULES) <= set(native_map), "native anchor coverage")
    require(
        native_bindings.get("consumerCallsitesProved") is False
        and native_bindings.get("productExecutionProved") is False,
        "upstream native nonclaims drifted",
    )

    verify_baseline(truth)
    mapped = 0
    unresolved = 0
    for row in modules:
        module = row["module"]
        require(row.get("maturity") in ALLOWED_MATURITY, f"{module} maturity")
        require(row.get("rootState") in ALLOWED_ROOT_STATE, f"{module} root state")

        binding = source_map[module]
        roots = binding.get("declaredRoots")
        require(isinstance(roots, list) and roots, f"{module} declared roots")
        for root in roots:
            require((ROOT / root).exists(), f"{module} missing root {root}")
        verify_native_anchor(module, native_map[module])

        operations = row.get("operations")
        require(isinstance(operations, list), f"{module} operations")
        require(
            [op.get("designOperation") for op in operations]
            == EXPECTED_OPERATIONS[module],
            f"{module} operation coverage/order",
        )
        for operation in operations:
            verify_operation(operation, module)
            if operation["state"] in {"planned", "mapping_required"}:
                unresolved += 1
            else:
                mapped += 1

        require(
            row.get("productionCallerState") == "unproved",
            f"{module} unsupported production caller claim",
        )
        require(
            row.get("productExecutionState") == "unproved",
            f"{module} unsupported product execution claim",
        )
        for key in ["stateDisposition", "terminalObserverDisposition"]:
            require(
                isinstance(row.get(key), str) and len(row[key]) >= 20,
                f"{module} {key}",
            )
        gaps = row.get("residualGaps")
        require(
            isinstance(gaps, list)
            and gaps
            and all(isinstance(gap, str) and len(gap) >= 12 for gap in gaps),
            f"{module} residual gap disclosure",
        )
        if row["maturity"] in NO_RUNTIME_MATURITY:
            require(
                all(op["state"] != "implemented" for op in operations),
                f"{module} scaffold cannot claim implemented runtime operation",
            )

    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_LANE_B_IMPLEMENTATION_TRUTH",
                "modules": len(modules),
                "mappedOrBoundedOperations": mapped,
                "plannedOrUnmappedOperations": unresolved,
                "targetDesignImplementationClosed": False,
                "productionConsumerCallsitesProved": False,
                "productExecutionProved": False,
            },
            sort_keys=True,
        )
    )
    return 0


def self_test() -> int:
    require(pairs([("a", 1), ("b", 2)]) == {"a": 1, "b": 2}, "pairs")
    try:
        pairs([("a", 1), ("a", 2)])
    except Invalid:
        pass
    else:
        raise Invalid("duplicate-key self-test")
    require(len(EXPECTED_MODULES) == 11, "module fixture")
    require(set(EXPECTED_OPERATIONS) == set(EXPECTED_MODULES), "operation fixture")
    require(NO_RUNTIME_MATURITY <= ALLOWED_MATURITY, "maturity fixture")
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_LANE_B_IMPLEMENTATION_TRUTH_SELF_TEST",
                "cases": [
                    "duplicate_json_keys",
                    "module_closed_world",
                    "operation_closed_world",
                    "maturity_vocabulary",
                ],
            },
            sort_keys=True,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["verify", "self-test"])
    args = parser.parse_args()
    try:
        return verify() if args.command == "verify" else self_test()
    except Invalid as exc:
        raise SystemExit(f"FAIL_HEPTA_LANE_B_IMPLEMENTATION_TRUTH: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
