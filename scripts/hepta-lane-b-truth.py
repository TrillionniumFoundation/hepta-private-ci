#!/usr/bin/env python3
"""Fail-closed validator for Lane B truth inside a composed all-lanes candidate."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = Path(__file__).with_name("hepta-lane-b-truth-core.py")
SPEC = importlib.util.spec_from_file_location("hepta_lane_b_truth_core", CORE_PATH)
if SPEC is None or SPEC.loader is None:  # pragma: no cover - import invariant
    raise RuntimeError(f"cannot load {CORE_PATH}")
CORE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CORE)

Invalid = CORE.Invalid
pairs = CORE.pairs
require = CORE.require
run_git = CORE.run_git
load_json = CORE.load_json
verify_operation = CORE.verify_operation
symbol_occurrences = CORE.symbol_occurrences
MODULES = CORE.MODULES
EXPECTED_OPERATIONS = CORE.EXPECTED_OPERATIONS
TRUTH_PATH = ROOT / "qualification/lane-b/LANE_B_IMPLEMENTATION_TRUTH.json"
HEX40 = re.compile(r"[0-9a-f]{40}")


def verify_baseline_provenance(truth: dict[str, Any]) -> tuple[str, str]:
    """Bind the declared Lane B source baseline without imposing PR topology."""
    baseline = truth.get("baseline")
    require(isinstance(baseline, dict), "truth baseline")
    commit = baseline.get("commit")
    tree = baseline.get("tree")
    require(
        isinstance(commit, str) and HEX40.fullmatch(commit) is not None,
        "baseline commit",
    )
    require(
        isinstance(tree, str) and HEX40.fullmatch(tree) is not None,
        "baseline tree",
    )
    require(run_git("rev-parse", f"{commit}^{{tree}}") == tree, "baseline tree mismatch")
    return commit, tree


def verify() -> int:
    truth = load_json(TRUTH_PATH)
    require(
        truth.get("documentClass") == "repository_controlled_truth_boundary",
        "truth document class",
    )
    require(
        truth.get("allowedOperationStates")
        == ["implemented", "implemented_partial", "boundary_only", "planned"],
        "operation-state vocabulary/order",
    )
    rules = truth.get("rules")
    require(isinstance(rules, dict), "truth rules")
    for key in (
        "rootMaterializationIsNotImplementation",
        "designOperationIsNotNativeSymbol",
        "libraryReachabilityIsNotProductionCallsite",
        "callerSuppliedObservationIsNotTerminalProof",
        "qualificationOnlyIsNotProduction",
        "oneSourceBlobIsNotModuleClosure",
        "externalEvidenceCannotBeSelfIssued",
        "mappedSymbolMustBeUniqueInDeclaredPath",
        "mappedSourceMustBeInsideAllowedOwnerRoots",
        "plannedOperationMustNotInventSource",
    ):
        require(rules.get(key) is True, f"missing truth rule {key}")

    baseline_commit, baseline_tree = verify_baseline_provenance(truth)
    manifest_view = {
        "planId": truth.get("planId"),
        "planVersion": truth.get("planVersion"),
        "baseCommit": baseline_commit,
        "baseTree": baseline_tree,
    }
    mapped, planned = CORE.verify_truth(truth, manifest_view)
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_LANE_B_IMPLEMENTATION_TRUTH_V2",
                "baselineCommit": baseline_commit,
                "baselineTree": baseline_tree,
                "baselineRelationship": "provenance_object",
                "modules": len(MODULES),
                "operations": mapped + planned,
                "mappedOperations": mapped,
                "plannedOperations": planned,
                "repositoryTruthModelClosed": True,
                "currentMappingDebtClosed": True,
                "targetDesignImplementationClosed": False,
                "productExecutionProved": False,
                "independentAcceptanceProved": False,
            },
            sort_keys=True,
        )
    )
    return 0


def self_test() -> int:
    CORE.self_test()
    require(
        len(MODULES) == 11 and sum(map(len, EXPECTED_OPERATIONS.values())) == 39,
        "closed sets",
    )
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_LANE_B_IMPLEMENTATION_TRUTH_SELF_TEST_V2",
                "modules": 11,
                "operations": 39,
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
    except (Invalid, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"FAIL_HEPTA_LANE_B_IMPLEMENTATION_TRUTH_V2: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
