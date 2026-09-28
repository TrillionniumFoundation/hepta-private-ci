#!/usr/bin/env python3
"""Project objective.compiler source facts and observed receipts into one status view.

The checked-in current-state manifest contains static source facts and policy only.
Dynamic source-head, synthetic-merge and target-host observations are accepted
solely from exact artifacts bound to the requested source commit/tree. The
projection never grants independent acceptance, selected deployment-host
approval, activation, promotion or release.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

SHA = re.compile(r"[0-9a-f]{40}\Z")
LOG_SHA = re.compile(r"[0-9a-f]{64}\Z")
CURRENT_SCHEMA = "hepta.objective-compiler-current-state.v2"
PROJECTION_SCHEMA = "hepta.objective-evidence-projection.v2"
RESOURCE_SCHEMA = "hepta.objective-command-resource-observation.v1"
DYNAMIC_SOURCE_FIELDS = {
    "currentHeadQualification",
    "syntheticMergeQualification",
    "targetHostQualification",
    "checksPassed",
    "measurementObserved",
}


def load(path: Path) -> dict[str, Any]:
    def unique(items: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in items:
            if key in value:
                raise ValueError(f"duplicate JSON key in {path}: {key}")
            value[key] = item
        return value

    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def nonempty_strings(value: Any, field: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item for item in value)
    ):
        raise ValueError(f"{field} must be a non-empty string list")
    return value


def current_state_projection(path: Path) -> dict[str, Any]:
    manifest = load(path)
    if (
        manifest.get("schema") != CURRENT_SCHEMA
        or manifest.get("schemaVersion") != 2
        or manifest.get("module") != "objective.compiler"
    ):
        raise ValueError("unexpected objective current-state schema or identity")
    state = manifest.get("implementationState")
    required_state = {
        "core",
        "productComposition",
        "semanticHardening",
        "qualificationEvidence",
        "independentAcceptance",
        "canaryPromotionRollback",
    }
    if (
        not isinstance(state, dict)
        or set(state) != required_state
        or any(not isinstance(state[key], str) or not state[key] for key in required_state)
    ):
        raise ValueError("objective current-state implementationState is incomplete")
    if DYNAMIC_SOURCE_FIELDS.intersection(state):
        raise ValueError("dynamic qualification fields are forbidden in source state")

    truth = manifest.get("truth")
    truth_keys = {"productionImplementation", "accepted", "activated", "released"}
    if (
        not isinstance(truth, dict)
        or set(truth) != truth_keys
        or any(type(truth[key]) is not bool for key in truth_keys)
    ):
        raise ValueError("objective current-state truth is invalid")
    if any(truth.values()):
        raise ValueError("source state cannot grant production, acceptance or release")

    contract = manifest.get("evidenceProjection")
    if (
        not isinstance(contract, dict)
        or contract.get("schema") != PROJECTION_SCHEMA
        or contract.get("producer") != "scripts/hepta-objective-evidence-project.py"
        or contract.get("manualPassFieldsForbidden") is not True
    ):
        raise ValueError("objective evidence-projection contract is invalid")
    dynamic_claims = nonempty_strings(contract.get("dynamicClaims"), "dynamicClaims")
    if set(dynamic_claims) != {
        "sourceHeadQualification",
        "syntheticMergeQualification",
        "targetHostMeasurement",
    }:
        raise ValueError("objective evidence-projection dynamic claim set is invalid")

    return {
        "artifactSha256": sha256(path),
        "schema": manifest["schema"],
        "schemaVersion": manifest["schemaVersion"],
        "implementationState": state,
        "truth": truth,
        "requiredChecks": nonempty_strings(
            manifest.get("requiredChecks"), "requiredChecks"
        ),
        "externalGates": nonempty_strings(
            manifest.get("externalGates"), "externalGates"
        ),
        "projectionContract": contract,
    }


def candidate_state(receipt: dict[str, Any], kind: str) -> str:
    candidates = receipt.get("candidates")
    if not isinstance(candidates, list):
        return "failed"
    matching = [
        item
        for item in candidates
        if isinstance(item, dict) and item.get("kind") == kind
    ]
    if len(matching) != 1:
        return "failed"
    candidate = matching[0]
    checks = candidate.get("checks")
    if (
        candidate.get("clean") is True
        and isinstance(checks, list)
        and checks
        and all(
            isinstance(check, dict)
            and check.get("status") == "completed"
            and check.get("exitCode") == 0
            and isinstance(check.get("logSha256"), str)
            and LOG_SHA.fullmatch(check["logSha256"])
            for check in checks
        )
    ):
        return "passed"
    return "failed"


def exact_projection(
    path: Path, source_commit: str, source_tree: str
) -> dict[str, Any]:
    receipt = load(path)
    if receipt.get("schema") != "hepta.objective.exact-execution.v1":
        raise ValueError("unexpected exact-execution schema")
    if (
        receipt.get("sourceCommit") != source_commit
        or receipt.get("sourceTree") != source_tree
    ):
        raise ValueError("exact-execution source identity mismatch")
    source_state = candidate_state(receipt, "source-head")
    merge_state = candidate_state(receipt, "synthetic-merge")
    errors = receipt.get("errors") if isinstance(receipt.get("errors"), list) else []
    derived_pass = source_state == merge_state == "passed" and not errors
    if (receipt.get("checksPassed") is True) != derived_pass:
        raise ValueError("exact-execution checksPassed disagrees with observed checks")
    return {
        "artifactSha256": sha256(path),
        "runId": receipt.get("runId"),
        "runAttempt": receipt.get("runAttempt"),
        "workflowCommit": receipt.get("workflowCommit"),
        "workflowRef": receipt.get("workflowRef"),
        "sourceHeadQualification": source_state,
        "syntheticMergeQualification": merge_state,
        "checksPassed": derived_pass,
        "errors": errors,
    }


def valid_resource_observation(value: Any) -> bool:
    if not isinstance(value, dict) or value.get("schema") != RESOURCE_SCHEMA:
        return False
    if not isinstance(value.get("scope"), str) or not value["scope"]:
        return False
    for field in (
        "peakResidentSetBytes",
        "userCpuNanoseconds",
        "systemCpuNanoseconds",
        "wallNanoseconds",
        "minorPageFaults",
        "majorPageFaults",
        "voluntaryContextSwitches",
        "involuntaryContextSwitches",
    ):
        if type(value.get(field)) is not int or value[field] < 0:
            return False
    return value["wallNanoseconds"] > 0


def target_projection(
    path: Path, source_commit: str, source_tree: str
) -> dict[str, Any]:
    receipt = load(path)
    if receipt.get("schema") != "hepta.objective-target-host-evidence.v1":
        raise ValueError("unexpected target-measurement schema")
    if (
        receipt.get("sourceCommit") != source_commit
        or receipt.get("sourceTree") != source_tree
    ):
        raise ValueError("target-measurement source identity mismatch")
    measurements = receipt.get("measurements")
    expected_paths = {
        "ordinary_authenticated_admission_compile",
        "maximum_conflict_extraction",
        "signed_objective_daemon_round_trip",
    }
    if not isinstance(measurements, list) or len(measurements) != len(expected_paths):
        raise ValueError("target measurement must contain three bounded workloads")
    by_path = {
        item.get("path"): item for item in measurements if isinstance(item, dict)
    }
    if set(by_path) != expected_paths or len(by_path) != len(measurements):
        raise ValueError("target measurement workload identities are incomplete")
    if not all(
        valid_resource_observation(item.get("fixtureProcessResources"))
        for item in by_path.values()
    ):
        raise ValueError("target measurement lacks isolated fixture resources")
    interpretation = receipt.get("interpretation")
    if (
        not isinstance(interpretation, dict)
        or interpretation.get("fixtureResourcesIsolatedByFreshHelperProcess") is not True
        or interpretation.get("memoryIsNotPerInternalPhaseAllocation") is not True
        or interpretation.get("dynamicAuthorizationCachingAllowed") is not False
        or interpretation.get("atomicAppendCheckpointHandoffBoundaryPreserved") is not True
    ):
        raise ValueError("target measurement interpretation boundary is incomplete")
    return {
        "artifactSha256": sha256(path),
        "runId": receipt.get("workflowRunId"),
        "runAttempt": receipt.get("workflowRunAttempt"),
        "workflowCommit": receipt.get("workflowCommit"),
        "workflowRef": receipt.get("workflowRef"),
        "hostProfileId": receipt.get("hostProfileId"),
        "measurementObserved": True,
        "measurementCount": len(measurements),
        "workloadPaths": sorted(expected_paths),
        "resourceObservation": "isolated_fixture_process_tree",
        "selectedDeploymentHostAccepted": False,
        "storageQualificationProved": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-tree", required=True)
    parser.add_argument("--current-state", type=Path, required=True)
    parser.add_argument("--exact-execution", type=Path)
    parser.add_argument("--target-measurement", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if not SHA.fullmatch(args.source_commit) or not SHA.fullmatch(args.source_tree):
        parser.error("source commit and tree must be complete lowercase SHA-1 identities")
    if args.exact_execution is None and args.target_measurement is None:
        parser.error("at least one evidence input is required")

    source = current_state_projection(args.current_state)
    exact = (
        exact_projection(args.exact_execution, args.source_commit, args.source_tree)
        if args.exact_execution is not None
        else {
            "sourceHeadQualification": "unverified",
            "syntheticMergeQualification": "unverified",
            "checksPassed": False,
        }
    )
    target = (
        target_projection(args.target_measurement, args.source_commit, args.source_tree)
        if args.target_measurement is not None
        else {
            "measurementObserved": False,
            "selectedDeploymentHostAccepted": False,
            "storageQualificationProved": False,
        }
    )
    status = {
        "core": source["implementationState"]["core"],
        "productComposition": source["implementationState"]["productComposition"],
        "semanticHardening": source["implementationState"]["semanticHardening"],
        "sourceHeadQualification": exact["sourceHeadQualification"],
        "syntheticMergeQualification": exact["syntheticMergeQualification"],
        "targetHostMeasurement": (
            "observed" if target["measurementObserved"] else "unverified"
        ),
        "selectedDeploymentHostQualification": "unverified",
        "independentAcceptance": "unverified",
        "operatorAcceptance": "unverified",
        "canaryPromotionRollback": source["implementationState"][
            "canaryPromotionRollback"
        ],
    }
    projection = {
        "schema": PROJECTION_SCHEMA,
        "schemaVersion": 2,
        "module": "objective.compiler",
        "sourceCommit": args.source_commit,
        "sourceTree": args.source_tree,
        "sourceState": source,
        "executionEvidence": {
            "exactExecution": exact,
            "targetHostMeasurement": target,
        },
        "status": status,
        "truth": source["truth"],
        "claimBoundary": (
            "static source facts plus authenticated artifact observations only; no "
            "independent acceptance, selected deployment-host approval, activation, "
            "promotion or release authority"
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(projection, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(args.output)
    print(json.dumps(projection, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
