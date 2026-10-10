#!/usr/bin/env python3
"""Fail-closed admission verifier for kernel.authority production evidence.

This verifier validates a self-contained external evidence bundle. It does not
manufacture trusted time, anti-rollback, transport, key custody, performance
measurements, operator acceptance, activation or release authority.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "hepta.kernel-authority-production-evidence.v1"
SCHEMA_VERSION = 1
MAX_NODES = 256
MAX_CLOCK_UNCERTAINTY_MS = 60_000
REQUIRED_SCENARIOS = {"normal", "delayed", "partition", "restart"}
REQUIRED_CAPACITY_POINTS = {"empty", "1k", "8k", "90_percent", "max"}
REQUIRED_FAULT_CASES = {
    "before_external_frontier_cas",
    "after_external_cas_before_local_temp_write",
    "after_temp_fsync_before_rename",
    "after_rename_before_directory_fsync",
    "after_successful_local_commit",
    "during_prune",
    "during_epoch_rollover",
    "restart_with_older_local_snapshot",
}
REQUIRED_KEY_ROLES = {"issuer", "approver", "distributor"}


class Invalid(ValueError):
    pass


def need(condition: bool, message: str) -> None:
    if not condition:
        raise Invalid(message)


def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in items:
        need(key not in out, f"duplicate JSON key: {key}")
        out[key] = value
    return out


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    except Exception as exc:
        raise Invalid(f"{path}: invalid JSON: {exc}") from exc
    need(isinstance(value, dict), f"{path}: expected object")
    return value


def exact_keys(value: dict[str, Any], keys: set[str], label: str) -> None:
    need(set(value) == keys, f"{label}: fields must be exactly {sorted(keys)}")


def nonempty(value: Any, label: str) -> str:
    need(isinstance(value, str) and value.strip() == value and bool(value), f"{label}: non-empty string")
    need(len(value.encode("utf-8")) <= 256, f"{label}: too long")
    need(all(ord(char) >= 32 and ord(char) != 127 for char in value), f"{label}: control character")
    return value


def sha256_hex(value: Any, label: str) -> str:
    text = nonempty(value, label)
    need(len(text) == 64 and all(char in "0123456789abcdef" for char in text), f"{label}: lowercase sha256")
    need(text != "0" * 64, f"{label}: zero digest")
    return text


def git_sha(value: Any, label: str) -> str:
    text = nonempty(value, label)
    need(len(text) == 40 and all(char in "0123456789abcdef" for char in text), f"{label}: lowercase git sha")
    need(text != "0" * 40, f"{label}: zero git sha")
    return text


def positive_int(value: Any, label: str, *, maximum: int | None = None) -> int:
    need(type(value) is int and value > 0, f"{label}: positive integer")
    if maximum is not None:
        need(value <= maximum, f"{label}: exceeds maximum")
    return value


def true(value: Any, label: str) -> None:
    need(value is True, f"{label}: must be true")


def canonical_artifact(root: Path, relative: Any) -> Path:
    text = nonempty(relative, "artifact path")
    need("\\" not in text and ":" not in text, f"artifact path: non-canonical {text!r}")
    parts = text.split("/")
    need(all(part not in {"", ".", ".."} for part in parts), f"artifact path: unsafe {text!r}")
    candidate = root
    for part in parts:
        candidate = candidate / part
        need(not candidate.is_symlink(), f"artifact path: symlink {text!r}")
    resolved_root = root.resolve()
    resolved = candidate.resolve()
    need(resolved.is_relative_to(resolved_root), f"artifact path: escape {text!r}")
    need(resolved.relative_to(resolved_root).as_posix() == text, f"artifact path: alias {text!r}")
    need(candidate.is_file(), f"artifact path: missing regular file {text!r}")
    return candidate


def artifact_index(root: Path, rows: Any) -> dict[str, str]:
    need(isinstance(rows, list) and rows, "artifacts: non-empty array")
    out: dict[str, str] = {}
    for index, row in enumerate(rows):
        need(isinstance(row, dict), f"artifacts[{index}]: object")
        exact_keys(row, {"path", "sha256"}, f"artifacts[{index}]")
        path = nonempty(row["path"], f"artifacts[{index}].path")
        digest = sha256_hex(row["sha256"], f"artifacts[{index}].sha256")
        need(path not in out, f"artifacts: duplicate path {path}")
        file_path = canonical_artifact(root, path)
        actual = hashlib.sha256(file_path.read_bytes()).hexdigest()
        need(actual == digest, f"artifact digest mismatch: {path}")
        out[path] = digest
    return out


def receipt_ref(value: Any, artifacts: dict[str, str], label: str) -> str:
    path = nonempty(value, label)
    need(path in artifacts, f"{label}: missing from artifacts")
    return path


def validate(document: dict[str, Any], bundle_root: Path, expected_commit: str | None, expected_tree: str | None) -> None:
    exact_keys(
        document,
        {
            "schema",
            "schemaVersion",
            "candidate",
            "authority",
            "trustedTime",
            "antiRollback",
            "revocationDistribution",
            "keyCustody",
            "capacity",
            "operatorAcceptance",
            "artifacts",
        },
        "bundle",
    )
    need(document["schema"] == SCHEMA and document["schemaVersion"] == SCHEMA_VERSION, "bundle: schema")

    candidate = document["candidate"]
    need(isinstance(candidate, dict), "candidate: object")
    exact_keys(candidate, {"commit", "tree"}, "candidate")
    commit = git_sha(candidate["commit"], "candidate.commit")
    tree = git_sha(candidate["tree"], "candidate.tree")
    if expected_commit is not None:
        need(commit == expected_commit, "candidate.commit: expected exact source")
    if expected_tree is not None:
        need(tree == expected_tree, "candidate.tree: expected exact tree")

    artifacts = artifact_index(bundle_root, document["artifacts"])

    authority = document["authority"]
    need(isinstance(authority, dict), "authority: object")
    exact_keys(authority, {"ownerId", "stateSchema"}, "authority")
    nonempty(authority["ownerId"], "authority.ownerId")
    positive_int(authority["stateSchema"], "authority.stateSchema")

    clock = document["trustedTime"]
    need(isinstance(clock, dict), "trustedTime: object")
    exact_keys(
        clock,
        {"backendId", "qualificationReceipt", "maxClockUncertaintyMs", "failClosed", "rollbackIndependent"},
        "trustedTime",
    )
    nonempty(clock["backendId"], "trustedTime.backendId")
    receipt_ref(clock["qualificationReceipt"], artifacts, "trustedTime.qualificationReceipt")
    positive_int(clock["maxClockUncertaintyMs"], "trustedTime.maxClockUncertaintyMs", maximum=MAX_CLOCK_UNCERTAINTY_MS)
    true(clock["failClosed"], "trustedTime.failClosed")
    true(clock["rollbackIndependent"], "trustedTime.rollbackIndependent")

    frontier = document["antiRollback"]
    need(isinstance(frontier, dict), "antiRollback: object")
    exact_keys(
        frontier,
        {"backendId", "qualificationReceipt", "durableCas", "conflictExclusion", "noGenesisFallback", "restoredSnapshotRejected"},
        "antiRollback",
    )
    nonempty(frontier["backendId"], "antiRollback.backendId")
    receipt_ref(frontier["qualificationReceipt"], artifacts, "antiRollback.qualificationReceipt")
    for field in ("durableCas", "conflictExclusion", "noGenesisFallback", "restoredSnapshotRejected"):
        true(frontier[field], f"antiRollback.{field}")

    distribution = document["revocationDistribution"]
    need(isinstance(distribution, dict), "revocationDistribution: object")
    exact_keys(
        distribution,
        {
            "transportId",
            "qualificationReceipt",
            "enrolledNodes",
            "feedLifetimeMs",
            "convergenceSlaMs",
            "scenarios",
            "allCurrentHeadAcknowledged",
            "staleFeedFailClosed",
        },
        "revocationDistribution",
    )
    nonempty(distribution["transportId"], "revocationDistribution.transportId")
    receipt_ref(distribution["qualificationReceipt"], artifacts, "revocationDistribution.qualificationReceipt")
    nodes = distribution["enrolledNodes"]
    need(isinstance(nodes, list) and 0 < len(nodes) <= MAX_NODES, "revocationDistribution.enrolledNodes")
    normalized_nodes = [nonempty(node, "revocationDistribution.enrolledNodes[]") for node in nodes]
    need(len(set(normalized_nodes)) == len(normalized_nodes), "revocationDistribution.enrolledNodes: duplicates")
    feed_lifetime = positive_int(distribution["feedLifetimeMs"], "revocationDistribution.feedLifetimeMs")
    convergence_sla = positive_int(distribution["convergenceSlaMs"], "revocationDistribution.convergenceSlaMs")
    need(convergence_sla <= feed_lifetime, "revocationDistribution: SLA exceeds feed lifetime")
    scenarios = distribution["scenarios"]
    need(isinstance(scenarios, list), "revocationDistribution.scenarios: array")
    seen: set[str] = set()
    for index, scenario in enumerate(scenarios):
        need(isinstance(scenario, dict), f"revocationDistribution.scenarios[{index}]: object")
        exact_keys(scenario, {"name", "receipt", "maxDeliveryMs", "maxAckMs", "withinSla"}, f"revocationDistribution.scenarios[{index}]")
        name = nonempty(scenario["name"], f"revocationDistribution.scenarios[{index}].name")
        need(name in REQUIRED_SCENARIOS and name not in seen, f"revocationDistribution.scenarios[{index}].name")
        seen.add(name)
        receipt_ref(scenario["receipt"], artifacts, f"revocationDistribution.scenarios[{index}].receipt")
        need(type(scenario["maxDeliveryMs"]) is int and scenario["maxDeliveryMs"] >= 0, f"revocationDistribution.scenarios[{index}].maxDeliveryMs")
        need(type(scenario["maxAckMs"]) is int and scenario["maxAckMs"] >= 0, f"revocationDistribution.scenarios[{index}].maxAckMs")
        true(scenario["withinSla"], f"revocationDistribution.scenarios[{index}].withinSla")
    need(seen == REQUIRED_SCENARIOS, "revocationDistribution.scenarios: incomplete")
    true(distribution["allCurrentHeadAcknowledged"], "revocationDistribution.allCurrentHeadAcknowledged")
    true(distribution["staleFeedFailClosed"], "revocationDistribution.staleFeedFailClosed")

    custody = document["keyCustody"]
    need(isinstance(custody, list), "keyCustody: array")
    roles: set[str] = set()
    for index, role in enumerate(custody):
        need(isinstance(role, dict), f"keyCustody[{index}]: object")
        exact_keys(
            role,
            {
                "role",
                "custodyBackendId",
                "activeKeyIds",
                "qualificationReceipt",
                "rotationReceipt",
                "compromiseReceipt",
                "historicalAuditRetained",
                "applicationPrivateKeyExposure",
            },
            f"keyCustody[{index}]",
        )
        name = nonempty(role["role"], f"keyCustody[{index}].role")
        need(name in REQUIRED_KEY_ROLES and name not in roles, f"keyCustody[{index}].role")
        roles.add(name)
        nonempty(role["custodyBackendId"], f"keyCustody[{index}].custodyBackendId")
        key_ids = role["activeKeyIds"]
        need(isinstance(key_ids, list) and key_ids, f"keyCustody[{index}].activeKeyIds")
        normalized = [nonempty(key, f"keyCustody[{index}].activeKeyIds[]") for key in key_ids]
        need(len(set(normalized)) == len(normalized), f"keyCustody[{index}].activeKeyIds: duplicates")
        for field in ("qualificationReceipt", "rotationReceipt", "compromiseReceipt"):
            receipt_ref(role[field], artifacts, f"keyCustody[{index}].{field}")
        true(role["historicalAuditRetained"], f"keyCustody[{index}].historicalAuditRetained")
        need(role["applicationPrivateKeyExposure"] == "role_process_only", f"keyCustody[{index}].applicationPrivateKeyExposure")
    need(roles == REQUIRED_KEY_ROLES, "keyCustody: incomplete roles")

    capacity = document["capacity"]
    need(isinstance(capacity, dict), "capacity: object")
    exact_keys(capacity, {"qualificationReceipt", "measuredPoints", "faultInjectionCases", "latencyBudgetPass", "reserveAlertDemonstrated"}, "capacity")
    receipt_ref(capacity["qualificationReceipt"], artifacts, "capacity.qualificationReceipt")
    points = capacity["measuredPoints"]
    need(isinstance(points, list) and set(points) == REQUIRED_CAPACITY_POINTS and len(points) == len(REQUIRED_CAPACITY_POINTS), "capacity.measuredPoints")
    faults = capacity["faultInjectionCases"]
    need(isinstance(faults, list) and set(faults) == REQUIRED_FAULT_CASES and len(faults) == len(REQUIRED_FAULT_CASES), "capacity.faultInjectionCases")
    true(capacity["latencyBudgetPass"], "capacity.latencyBudgetPass")
    true(capacity["reserveAlertDemonstrated"], "capacity.reserveAlertDemonstrated")

    acceptance = document["operatorAcceptance"]
    need(isinstance(acceptance, dict), "operatorAcceptance: object")
    exact_keys(acceptance, {"reviewerId", "receipt", "acceptedCandidateCommit", "acceptedCandidateTree", "accepted"}, "operatorAcceptance")
    nonempty(acceptance["reviewerId"], "operatorAcceptance.reviewerId")
    receipt_ref(acceptance["receipt"], artifacts, "operatorAcceptance.receipt")
    need(git_sha(acceptance["acceptedCandidateCommit"], "operatorAcceptance.acceptedCandidateCommit") == commit, "operatorAcceptance: commit mismatch")
    need(git_sha(acceptance["acceptedCandidateTree"], "operatorAcceptance.acceptedCandidateTree") == tree, "operatorAcceptance: tree mismatch")
    true(acceptance["accepted"], "operatorAcceptance.accepted")


def current_identity(expected_sha: str) -> tuple[str, str]:
    commit = subprocess.run(
        ["git", "rev-parse", f"{expected_sha}^{{commit}}"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    tree = subprocess.run(
        ["git", "rev-parse", f"{commit}^{{tree}}"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    return git_sha(commit, "expected commit"), git_sha(tree, "expected tree")


def fixture(root: Path) -> dict[str, Any]:
    names = [
        "clock.json",
        "frontier.json",
        "revocation.json",
        "normal.json",
        "delayed.json",
        "partition.json",
        "restart.json",
        "issuer.json",
        "approver.json",
        "distributor.json",
        "issuer-rotation.json",
        "approver-rotation.json",
        "distributor-rotation.json",
        "issuer-compromise.json",
        "approver-compromise.json",
        "distributor-compromise.json",
        "capacity.json",
        "operator.json",
    ]
    artifacts = []
    for index, name in enumerate(names):
        path = root / name
        path.write_text(json.dumps({"evidence": index, "synthetic": True}) + "\n", encoding="utf-8")
        artifacts.append({"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    commit = "a" * 40
    tree = "b" * 40
    return {
        "schema": SCHEMA,
        "schemaVersion": SCHEMA_VERSION,
        "candidate": {"commit": commit, "tree": tree},
        "authority": {"ownerId": "security-authority", "stateSchema": 2},
        "trustedTime": {
            "backendId": "fixture-clock",
            "qualificationReceipt": "clock.json",
            "maxClockUncertaintyMs": 100,
            "failClosed": True,
            "rollbackIndependent": True,
        },
        "antiRollback": {
            "backendId": "fixture-frontier",
            "qualificationReceipt": "frontier.json",
            "durableCas": True,
            "conflictExclusion": True,
            "noGenesisFallback": True,
            "restoredSnapshotRejected": True,
        },
        "revocationDistribution": {
            "transportId": "fixture-wire",
            "qualificationReceipt": "revocation.json",
            "enrolledNodes": ["node-a", "node-b"],
            "feedLifetimeMs": 5_000,
            "convergenceSlaMs": 1_000,
            "scenarios": [
                {"name": name, "receipt": f"{name}.json", "maxDeliveryMs": 100, "maxAckMs": 100, "withinSla": True}
                for name in sorted(REQUIRED_SCENARIOS)
            ],
            "allCurrentHeadAcknowledged": True,
            "staleFeedFailClosed": True,
        },
        "keyCustody": [
            {
                "role": role,
                "custodyBackendId": f"fixture-{role}-kms",
                "activeKeyIds": [f"{role}-key-a", f"{role}-key-b"],
                "qualificationReceipt": f"{role}.json",
                "rotationReceipt": f"{role}-rotation.json",
                "compromiseReceipt": f"{role}-compromise.json",
                "historicalAuditRetained": True,
                "applicationPrivateKeyExposure": "role_process_only",
            }
            for role in sorted(REQUIRED_KEY_ROLES)
        ],
        "capacity": {
            "qualificationReceipt": "capacity.json",
            "measuredPoints": sorted(REQUIRED_CAPACITY_POINTS),
            "faultInjectionCases": sorted(REQUIRED_FAULT_CASES),
            "latencyBudgetPass": True,
            "reserveAlertDemonstrated": True,
        },
        "operatorAcceptance": {
            "reviewerId": "independent-reviewer",
            "receipt": "operator.json",
            "acceptedCandidateCommit": commit,
            "acceptedCandidateTree": tree,
            "accepted": True,
        },
        "artifacts": artifacts,
    }


def self_test() -> int:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        valid = fixture(root)
        validate(valid, root, "a" * 40, "b" * 40)

        hostile: list[tuple[str, dict[str, Any]]] = []
        value = copy.deepcopy(valid)
        value["trustedTime"]["failClosed"] = False
        hostile.append(("clock_not_fail_closed", value))
        value = copy.deepcopy(valid)
        value["antiRollback"]["restoredSnapshotRejected"] = False
        hostile.append(("rollback_not_rejected", value))
        value = copy.deepcopy(valid)
        value["revocationDistribution"]["enrolledNodes"].append("node-a")
        hostile.append(("duplicate_node", value))
        value = copy.deepcopy(valid)
        value["revocationDistribution"]["scenarios"] = value["revocationDistribution"]["scenarios"][:-1]
        hostile.append(("missing_partition_scenario", value))
        value = copy.deepcopy(valid)
        value["keyCustody"][0]["applicationPrivateKeyExposure"] = "general_application"
        hostile.append(("key_exposure", value))
        value = copy.deepcopy(valid)
        value["capacity"]["latencyBudgetPass"] = False
        hostile.append(("capacity_failed", value))
        value = copy.deepcopy(valid)
        value["operatorAcceptance"]["acceptedCandidateTree"] = "c" * 40
        hostile.append(("operator_tree_drift", value))
        value = copy.deepcopy(valid)
        value["artifacts"][0]["sha256"] = "d" * 64
        hostile.append(("artifact_substitution", value))

        for name, case in hostile:
            try:
                validate(case, root, "a" * 40, "b" * 40)
            except Invalid:
                continue
            raise Invalid(f"self-test accepted hostile case: {name}")

    print(json.dumps({"status": "PASS_KERNEL_AUTHORITY_PRODUCTION_EVIDENCE_SELF_TEST", "activationGranted": False}, sort_keys=True))
    return 0


def verify(path: Path, expected_sha: str) -> int:
    path = path.resolve()
    need(path.is_file(), "evidence path must be a file")
    commit, tree = current_identity(expected_sha)
    document = load_json(path)
    validate(document, path.parent, commit, tree)
    print(
        json.dumps(
            {
                "status": "PASS_KERNEL_AUTHORITY_PRODUCTION_EVIDENCE_ADMISSION",
                "candidateCommit": commit,
                "candidateTree": tree,
                "evidenceAdmitted": True,
                "activationGranted": False,
                "releaseGranted": False,
            },
            sort_keys=True,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("self-test")
    check = sub.add_parser("verify")
    check.add_argument("--evidence", required=True, type=Path)
    check.add_argument("--expected-sha", default="HEAD")
    args = parser.parse_args()
    if args.command == "self-test":
        return self_test()
    return verify(args.evidence, args.expected_sha)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Invalid as exc:
        raise SystemExit(f"FAIL_KERNEL_AUTHORITY_PRODUCTION_EVIDENCE: {exc}") from exc
