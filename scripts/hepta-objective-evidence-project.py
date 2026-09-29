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
import importlib.util
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


def qualification_commands() -> dict[str, list[str]]:
    # The existing read-only runner owns the check inventory. Do not maintain a
    # second, weaker list of commands in the receipt consumer.
    spec = importlib.util.spec_from_file_location(
        "objective_exact_contract", Path(__file__).with_name("hepta-objective-qualify-exact.py")
    )
    if spec is None or spec.loader is None:
        raise ValueError("exact execution contract is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return dict(module.commands())


def synthetic_commit_identity(tree: str, base: str, source: str) -> str:
    # Frozen author/date/message and parent order from deterministic_merge().
    # This checks the recorded merge identity, not independent merge correctness.
    actor = "Hepta immutable qualification <qualification@localhost> 946684800 +0000"
    text = (f"tree {tree}\nparent {base}\nparent {source}\n"
            f"author {actor}\ncommitter {actor}\n\n"
            f"objective qualification merge\nbase {base}\nsource {source}\n").encode()
    return hashlib.sha1(f"commit {len(text)}\0".encode() + text).hexdigest()


def candidate_state(receipt: dict[str, Any], kind: str, root: Path) -> str:
    candidates = receipt.get("candidates")
    if not isinstance(candidates, list) or receipt.get("sourceClean") is not True:
        return "failed"
    if any(not isinstance(item, dict) or item.get("kind") not in
           {"source-head", "synthetic-merge"} for item in candidates):
        return "failed"
    matching = [item for item in candidates if item.get("kind") == kind]
    if len(matching) != 1:
        return "failed"
    candidate = matching[0]
    commit, tree = candidate.get("commit"), candidate.get("tree")
    if any(not isinstance(value, str) or not SHA.fullmatch(value)
           for value in (commit, tree)):
        return "failed"
    if kind == "source-head":
        if (commit, tree) != (receipt["sourceCommit"], receipt["sourceTree"]):
            return "failed"
    else:
        base = receipt.get("mergeBase")
        if not isinstance(base, str) or not SHA.fullmatch(base):
            return "failed"
        if commit != synthetic_commit_identity(tree, base, receipt["sourceCommit"]):
            return "failed"
    expected = qualification_commands()
    checks = candidate.get("checks")
    if candidate.get("clean") is not True or not isinstance(checks, list):
        return "failed"
    if len(checks) != len(expected) or any(not isinstance(c, dict) for c in checks):
        return "failed"
    names = [c.get("name") for c in checks]
    if any(not isinstance(name, str) for name in names) or set(names) != set(expected):
        return "failed"
    root = root.resolve()
    directory = root / kind
    if directory.is_symlink() or not directory.is_dir():
        return "failed"
    for check in checks:
        name = check["name"]
        if (check.get("argv") != expected[name] or check.get("status") != "completed"
            or type(check.get("exitCode")) is not int or check["exitCode"] != 0
            or check.get("log") != f"{name}.log"
            or not isinstance(check.get("logSha256"), str)
            or not LOG_SHA.fullmatch(check["logSha256"])):
            return "failed"
        log = directory / f"{name}.log"
        if log.is_symlink() or not log.is_file() or sha256(log) != check["logSha256"]:
            return "failed"
    return "passed"


def exact_projection(
    path: Path, source_commit: str, source_tree: str
) -> dict[str, Any]:
    receipt = load(path)
    if receipt.get("schema") != "hepta.objective.exact-execution.v1":
        raise ValueError("unexpected exact-execution schema")
    if (receipt.get("sourceCommit") != source_commit
        or receipt.get("sourceTree") != source_tree):
        raise ValueError("exact-execution source identity mismatch")
    if type(receipt.get("checksPassed")) is not bool:
        raise ValueError("exact-execution checksPassed must be a Boolean")
    errors = receipt.get("errors")
    if not isinstance(errors, list) or any(not isinstance(error, str) for error in errors):
        raise ValueError("exact-execution errors must be an explicit string list")
    for field in ("selectedTargetHostAccepted", "independentAcceptance", "activated", "released"):
        if receipt.get(field) is not False:
            raise ValueError("exact execution cannot grant external acceptance or release")
    source_state = candidate_state(receipt, "source-head", path.parent)
    merge_state = candidate_state(receipt, "synthetic-merge", path.parent)
    derived_pass = source_state == merge_state == "passed" and not errors
    if receipt["checksPassed"] != derived_pass:
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


def validate_native_fixture(value: Any, source_commit: str, source_tree: str) -> None:
    if not isinstance(value, dict) or value.get("schema") != "hepta.objective-native-fixture.v1":
        raise ValueError("missing native fixture artifact identity")
    if value.get("sourceCommit") != source_commit or value.get("sourceTree") != source_tree:
        raise ValueError("native fixture candidate identity mismatch")
    if (type(value.get("exitCode")) is not int or value["exitCode"] != 0
        or value.get("artifactsUnchangedAfterExecution") is not True
        or value.get("buildCostsExcludedFromFixtureResources") is not True
        or value.get("nativeFfiQualificationProved") is not False):
        raise ValueError("native fixture execution boundary is incomplete")
    for field in ("cargoArtifactMessagesSha256", "testListSha256", "executionOutputSha256"):
        if not isinstance(value.get(field), str) or not LOG_SHA.fullmatch(value[field]):
            raise ValueError("native fixture log identity is invalid")
    artifacts = value.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError("native fixture lacks executable artifacts")
    paths = set()
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise ValueError("invalid native artifact")
        path = artifact.get("path")
        if not isinstance(path, str) or not path or path in paths:
            raise ValueError("native artifact path is missing or ambiguous")
        if (not isinstance(artifact.get("sha256"), str)
            or not LOG_SHA.fullmatch(artifact["sha256"])
            or type(artifact.get("sizeBytes")) is not int or artifact["sizeBytes"] <= 0):
            raise ValueError("invalid native artifact content identity")
        paths.add(path)
    executable, test = value.get("executable"), value.get("testName")
    if executable not in paths or not isinstance(test, str) or not test:
        raise ValueError("selected native executable or test is not bound")
    expected = [executable, test, "--ignored", "--exact", "--nocapture", "--test-threads=1"]
    if value.get("executionCommand") != expected:
        raise ValueError("resource sample must execute the exact prebuilt native test")
    build = value.get("buildCommand")
    if not isinstance(build, list) or build[:2] != ["cargo", "test"] or "--no-run" not in build:
        raise ValueError("native fixture build must be separate from execution")


def target_projection(
    path: Path, source_commit: str, source_tree: str
) -> dict[str, Any]:
    receipt = load(path)
    if receipt.get("schema") != "hepta.objective-target-host-evidence.v2":
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
    for item in by_path.values():
        validate_native_fixture(item.get("nativeFixture"), source_commit, source_tree)
    interpretation = receipt.get("interpretation")
    if (
        not isinstance(interpretation, dict)
        or interpretation.get("fixtureResourcesIsolatedByFreshHelperProcess") is not True
        or interpretation.get("memoryIsNotPerInternalPhaseAllocation") is not True
        or interpretation.get("buildCostsExcludedFromFixtureResources") is not True
        or interpretation.get("nativeArtifactsBoundBeforeAndAfterExecution") is not True
        or interpretation.get("nativeFfiQualificationProved") is not False
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
        "resourceObservation": "prebuilt_native_fixture_os_waited_child_counters",
        "nativeArtifactsBound": True,
        "nativeFfiQualificationProved": False,
        "buildCostsExcludedFromFixtureResources": True,
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
            "static source facts plus identity-bound artifact observations only; no "
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
