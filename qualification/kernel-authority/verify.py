#!/usr/bin/env python3
"""Fail-closed admission for kernel.authority production evidence.

Every retained receipt uses a canonical summary envelope. The verifier checks
exact candidate identity, parses the summary content, and cross-checks it against
bundle claims. It does not manufacture attested time, rollback resistance,
transport, key custody, target-host measurements, independent acceptance,
activation, or release authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, NamedTuple

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "hepta.kernel-authority-production-evidence.v2"
SCHEMA_VERSION = 2
RECEIPT_SCHEMA = "hepta.kernel-authority-evidence-receipt.v1"
RECEIPT_SCHEMA_VERSION = 1
MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_ARTIFACTS = 1024
MAX_BUNDLE_BYTES = 64 * 1024 * 1024
MAX_NODES = 256
MAX_CLOCK_UNCERTAINTY_MS = 60_000
MIN_LATENCY_SAMPLES = 100
SCENARIOS = {"normal", "delayed", "partition", "restart"}
POINTS = {"empty", "1k", "8k", "90_percent", "max"}
OPERATIONS = {
    "lease_put_replace",
    "lease_revoke",
    "lease_verify_final_use",
    "prune_1",
    "prune_128",
    "prune_1024",
    "epoch_rollover",
    "final_use_claim",
    "final_use_final_verify",
    "revocation_head_apply",
    "restart_open",
}
FAULTS = {
    "before_external_frontier_cas",
    "after_external_cas_before_local_temp_write",
    "after_temp_fsync_before_rename",
    "after_rename_before_directory_fsync",
    "after_successful_local_commit",
    "during_prune",
    "during_epoch_rollover",
    "restart_with_older_local_snapshot",
}
UNCERTAIN_FAULTS = {
    "after_external_cas_before_local_temp_write",
    "after_temp_fsync_before_rename",
    "during_prune",
    "during_epoch_rollover",
}
FAULT_OUTCOMES = {"reopen_succeeds", "fenced", "rollback_rejected"}
KEY_ROLES = {"issuer", "approver", "distributor"}


class Invalid(ValueError):
    pass


class ReceiptSpec(NamedTuple):
    path: str
    label: str
    kind: str
    data: dict[str, Any]


def need(ok: bool, message: str) -> None:
    if not ok:
        raise Invalid(message)


def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in items:
        need(key not in out, f"duplicate JSON key: {key}")
        out[key] = value
    return out


def bounded_bytes(path: Path) -> bytes:
    with path.open("rb") as stream:
        content = stream.read(MAX_JSON_BYTES + 1)
    need(len(content) <= MAX_JSON_BYTES, f"{path}: exceeds byte limit")
    return content


def invalid_constant(value: str) -> None:
    raise Invalid(f"non-finite JSON number: {value}")


def parse_json(content: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            content, object_pairs_hook=pairs, parse_constant=invalid_constant
        )
    except Exception as exc:
        raise Invalid(f"{label}: invalid JSON: {exc}") from exc
    need(isinstance(value, dict), f"{label}: expected object")
    return value


def load_json(path: Path) -> dict[str, Any]:
    return parse_json(bounded_bytes(path), str(path))


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def exact(value: dict[str, Any], keys: set[str], label: str) -> None:
    need(set(value) == keys, f"{label}: fields must be exactly {sorted(keys)}")


def text(value: Any, label: str) -> str:
    need(
        isinstance(value, str) and value and value.strip() == value,
        f"{label}: non-empty string",
    )
    need(len(value.encode()) <= 256, f"{label}: too long")
    need(
        all(ord(char) >= 32 and ord(char) != 127 for char in value),
        f"{label}: control character",
    )
    return value


def sha(value: Any, label: str, length: int) -> str:
    value = text(value, label)
    need(
        len(value) == length and all(c in "0123456789abcdef" for c in value),
        f"{label}: lowercase hex",
    )
    need(value != "0" * length, f"{label}: zero digest")
    return value


def git_sha(value: Any, label: str) -> str:
    return sha(value, label, 40)


def sha256(value: Any, label: str) -> str:
    return sha(value, label, 64)


def positive(value: Any, label: str, maximum: int | None = None) -> int:
    need(type(value) is int and value > 0, f"{label}: positive integer")
    if maximum is not None:
        need(value <= maximum, f"{label}: exceeds maximum")
    return value


def nonnegative(value: Any, label: str) -> int:
    need(type(value) is int and value >= 0, f"{label}: non-negative integer")
    return value


def must_true(value: Any, label: str) -> None:
    need(value is True, f"{label}: must be true")


def must_false(value: Any, label: str) -> None:
    need(value is False, f"{label}: must be false")


def canonical(value: Any, label: str) -> dict[str, Any]:
    need(isinstance(value, dict), f"{label}: object")
    try:
        value = json.loads(
            json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False),
            object_pairs_hook=pairs,
        )
    except Exception as exc:
        raise Invalid(f"{label}: non-canonical JSON: {exc}") from exc
    need(isinstance(value, dict), f"{label}: object")
    return value


def artifact_path(root: Path, relative: Any) -> Path:
    relative = text(relative, "artifact path")
    need(
        "\\" not in relative and ":" not in relative,
        f"artifact path: non-canonical {relative!r}",
    )
    parts = relative.split("/")
    need(
        all(part not in {"", ".", ".."} for part in parts),
        f"artifact path: unsafe {relative!r}",
    )
    candidate = root
    for part in parts:
        candidate /= part
        need(not candidate.is_symlink(), f"artifact path: symlink {relative!r}")
    resolved = candidate.resolve()
    need(resolved.is_relative_to(root.resolve()), f"artifact path: escape {relative!r}")
    need(
        resolved.relative_to(root.resolve()).as_posix() == relative,
        f"artifact path: alias {relative!r}",
    )
    need(candidate.is_file(), f"artifact path: missing file {relative!r}")
    return candidate


def artifact_index(root: Path, rows: Any) -> dict[str, bytes]:
    need(
        isinstance(rows, list) and 0 < len(rows) <= MAX_ARTIFACTS,
        "artifacts: bounded non-empty array",
    )
    out: dict[str, bytes] = {}
    total = 0
    for index, row in enumerate(rows):
        label = f"artifacts[{index}]"
        need(isinstance(row, dict), f"{label}: object")
        exact(row, {"path", "sha256"}, label)
        name = text(row["path"], f"{label}.path")
        need(name not in out, f"artifacts: duplicate path {name}")
        path = artifact_path(root, name)
        content = bounded_bytes(path)
        total += len(content)
        need(total <= MAX_BUNDLE_BYTES, "artifacts: aggregate byte limit exceeded")
        need(
            hashlib.sha256(content).hexdigest()
            == sha256(row["sha256"], f"{label}.sha256"),
            f"artifact digest mismatch: {name}",
        )
        out[name] = content
    return out


def claim_specs(document: dict[str, Any], commit: str, tree: str) -> list[ReceiptSpec]:
    specs: list[ReceiptSpec] = []
    add = lambda path, label, kind, data: specs.append(
        ReceiptSpec(
            text(path, label), label, kind, canonical(data, f"{label}.expected")
        )
    )

    authority = document["authority"]
    need(isinstance(authority, dict), "authority: object")
    exact(authority, {"ownerId", "stateSchema"}, "authority")
    owner = text(authority["ownerId"], "authority.ownerId")
    state_schema = positive(authority["stateSchema"], "authority.stateSchema")

    clock = document["trustedTime"]
    need(isinstance(clock, dict), "trustedTime: object")
    exact(
        clock,
        {
            "backendId",
            "qualificationReceipt",
            "maxClockUncertaintyMs",
            "failClosed",
            "rollbackIndependent",
        },
        "trustedTime",
    )
    clock_backend = text(clock["backendId"], "trustedTime.backendId")
    uncertainty = positive(
        clock["maxClockUncertaintyMs"],
        "trustedTime.maxClockUncertaintyMs",
        MAX_CLOCK_UNCERTAINTY_MS,
    )
    must_true(clock["failClosed"], "trustedTime.failClosed")
    must_true(clock["rollbackIndependent"], "trustedTime.rollbackIndependent")
    add(
        clock["qualificationReceipt"],
        "trustedTime.qualificationReceipt",
        "trusted_time_qualification",
        {
            "authorityOwnerId": owner,
            "authorityStateSchema": state_schema,
            "backendId": clock_backend,
            "maxClockUncertaintyMs": uncertainty,
            "failClosed": True,
            "rollbackIndependent": True,
        },
    )

    frontier = document["antiRollback"]
    need(isinstance(frontier, dict), "antiRollback: object")
    exact(
        frontier,
        {
            "backendId",
            "qualificationReceipt",
            "durableCas",
            "conflictExclusion",
            "noGenesisFallback",
            "restoredSnapshotRejected",
        },
        "antiRollback",
    )
    frontier_backend = text(frontier["backendId"], "antiRollback.backendId")
    for field in (
        "durableCas",
        "conflictExclusion",
        "noGenesisFallback",
        "restoredSnapshotRejected",
    ):
        must_true(frontier[field], f"antiRollback.{field}")
    add(
        frontier["qualificationReceipt"],
        "antiRollback.qualificationReceipt",
        "anti_rollback_qualification",
        {
            "authorityOwnerId": owner,
            "authorityStateSchema": state_schema,
            "backendId": frontier_backend,
            "durableCas": True,
            "conflictExclusion": True,
            "noGenesisFallback": True,
            "restoredSnapshotRejected": True,
        },
    )

    dist = document["revocationDistribution"]
    need(isinstance(dist, dict), "revocationDistribution: object")
    exact(
        dist,
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
    transport = text(dist["transportId"], "revocationDistribution.transportId")
    nodes = dist["enrolledNodes"]
    need(
        isinstance(nodes, list) and 0 < len(nodes) <= MAX_NODES,
        "revocationDistribution.enrolledNodes",
    )
    nodes = [text(node, "revocationDistribution.enrolledNodes[]") for node in nodes]
    need(
        len(set(nodes)) == len(nodes),
        "revocationDistribution.enrolledNodes: duplicates",
    )
    lifetime = positive(dist["feedLifetimeMs"], "revocationDistribution.feedLifetimeMs")
    sla = positive(dist["convergenceSlaMs"], "revocationDistribution.convergenceSlaMs")
    need(sla <= lifetime, "revocationDistribution: SLA exceeds feed lifetime")
    must_true(
        dist["allCurrentHeadAcknowledged"],
        "revocationDistribution.allCurrentHeadAcknowledged",
    )
    must_true(dist["staleFeedFailClosed"], "revocationDistribution.staleFeedFailClosed")
    add(
        dist["qualificationReceipt"],
        "revocationDistribution.qualificationReceipt",
        "revocation_distribution_qualification",
        {
            "transportId": transport,
            "enrolledNodes": nodes,
            "feedLifetimeMs": lifetime,
            "convergenceSlaMs": sla,
            "allCurrentHeadAcknowledged": True,
            "staleFeedFailClosed": True,
        },
    )
    scenarios = dist["scenarios"]
    need(isinstance(scenarios, list), "revocationDistribution.scenarios: array")
    seen: set[str] = set()
    for index, scenario in enumerate(scenarios):
        label = f"revocationDistribution.scenarios[{index}]"
        need(isinstance(scenario, dict), f"{label}: object")
        exact(
            scenario,
            {
                "name",
                "receipt",
                "maxDeliveryMs",
                "maxAckMs",
                "deliveredNodeCount",
                "acknowledgedNodeCount",
            },
            label,
        )
        name = text(scenario["name"], f"{label}.name")
        need(name in SCENARIOS and name not in seen, f"{label}.name")
        seen.add(name)
        delivery = nonnegative(scenario["maxDeliveryMs"], f"{label}.maxDeliveryMs")
        ack = nonnegative(scenario["maxAckMs"], f"{label}.maxAckMs")
        need(delivery <= ack, f"{label}: acknowledgement precedes delivery")
        need(ack <= sla, f"{label}: measured acknowledgement exceeds SLA")
        delivered = nonnegative(
            scenario["deliveredNodeCount"], f"{label}.deliveredNodeCount"
        )
        acknowledged = nonnegative(
            scenario["acknowledgedNodeCount"], f"{label}.acknowledgedNodeCount"
        )
        need(delivered == len(nodes), f"{label}: incomplete delivery set")
        need(acknowledged == delivered, f"{label}: incomplete acknowledgement set")
        add(
            scenario["receipt"],
            f"{label}.receipt",
            "revocation_scenario",
            {
                "transportId": transport,
                "enrolledNodes": nodes,
                "name": name,
                "maxDeliveryMs": delivery,
                "maxAckMs": ack,
                "deliveredNodeCount": delivered,
                "acknowledgedNodeCount": acknowledged,
            },
        )
    need(seen == SCENARIOS, "revocationDistribution.scenarios: incomplete")

    custody = document["keyCustody"]
    need(isinstance(custody, list), "keyCustody: array")
    seen_roles: set[str] = set()
    for index, role in enumerate(custody):
        label = f"keyCustody[{index}]"
        need(isinstance(role, dict), f"{label}: object")
        exact(
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
            label,
        )
        name = text(role["role"], f"{label}.role")
        need(name in KEY_ROLES and name not in seen_roles, f"{label}.role")
        seen_roles.add(name)
        backend = text(role["custodyBackendId"], f"{label}.custodyBackendId")
        keys = role["activeKeyIds"]
        need(isinstance(keys, list) and keys, f"{label}.activeKeyIds")
        keys = [text(key, f"{label}.activeKeyIds[]") for key in keys]
        need(len(set(keys)) == len(keys), f"{label}.activeKeyIds: duplicates")
        must_true(role["historicalAuditRetained"], f"{label}.historicalAuditRetained")
        need(
            role["applicationPrivateKeyExposure"] == "role_process_only",
            f"{label}.applicationPrivateKeyExposure",
        )
        common = {"role": name, "custodyBackendId": backend, "activeKeyIds": keys}
        add(
            role["qualificationReceipt"],
            f"{label}.qualificationReceipt",
            "key_custody_qualification",
            {
                **common,
                "historicalAuditRetained": True,
                "applicationPrivateKeyExposure": "role_process_only",
            },
        )
        add(
            role["rotationReceipt"],
            f"{label}.rotationReceipt",
            "key_rotation_rehearsal",
            {
                **common,
                "stagedOverlapRehearsed": True,
            },
        )
        add(
            role["compromiseReceipt"],
            f"{label}.compromiseReceipt",
            "key_compromise_response",
            {
                **common,
                "responseRehearsed": True,
            },
        )
    need(seen_roles == KEY_ROLES, "keyCustody: incomplete roles")

    capacity = document["capacity"]
    need(isinstance(capacity, dict), "capacity: object")
    exact(
        capacity,
        {"qualificationReceipt", "measurements", "faultResults", "reserveAlert"},
        "capacity",
    )
    measurements = capacity["measurements"]
    need(isinstance(measurements, list), "capacity.measurements: array")
    measured: set[tuple[str, str]] = set()
    for index, row in enumerate(measurements):
        label = f"capacity.measurements[{index}]"
        need(isinstance(row, dict), f"{label}: object")
        exact(
            row,
            {
                "point",
                "operation",
                "receipt",
                "sampleCount",
                "p50Ms",
                "p95Ms",
                "p99Ms",
                "latencyBudgetMs",
                "bytesWritten",
                "fsyncP99Ms",
                "peakRssBytes",
            },
            label,
        )
        point = text(row["point"], f"{label}.point")
        operation = text(row["operation"], f"{label}.operation")
        need(
            point in POINTS and operation in OPERATIONS,
            f"{label}: unknown point/operation",
        )
        need((point, operation) not in measured, f"{label}: duplicate point/operation")
        measured.add((point, operation))
        samples = positive(row["sampleCount"], f"{label}.sampleCount")
        need(samples >= MIN_LATENCY_SAMPLES, f"{label}: too few samples for p99")
        p50 = nonnegative(row["p50Ms"], f"{label}.p50Ms")
        p95 = nonnegative(row["p95Ms"], f"{label}.p95Ms")
        p99 = nonnegative(row["p99Ms"], f"{label}.p99Ms")
        budget = positive(row["latencyBudgetMs"], f"{label}.latencyBudgetMs")
        need(p50 <= p95 <= p99 <= budget, f"{label}: percentile/budget mismatch")
        written = nonnegative(row["bytesWritten"], f"{label}.bytesWritten")
        fsync = nonnegative(row["fsyncP99Ms"], f"{label}.fsyncP99Ms")
        need(fsync <= p99, f"{label}: fsync p99 exceeds total p99")
        rss = positive(row["peakRssBytes"], f"{label}.peakRssBytes")
        add(
            row["receipt"],
            f"{label}.receipt",
            "capacity_measurement",
            {
                "point": point,
                "operation": operation,
                "sampleCount": samples,
                "p50Ms": p50,
                "p95Ms": p95,
                "p99Ms": p99,
                "latencyBudgetMs": budget,
                "bytesWritten": written,
                "fsyncP99Ms": fsync,
                "peakRssBytes": rss,
            },
        )
    required_matrix = {
        (point, operation) for point in POINTS for operation in OPERATIONS
    }
    need(measured == required_matrix, "capacity.measurements: incomplete matrix")

    fault_rows = capacity["faultResults"]
    need(isinstance(fault_rows, list), "capacity.faultResults: array")
    seen_faults: set[str] = set()
    for index, row in enumerate(fault_rows):
        label = f"capacity.faultResults[{index}]"
        need(isinstance(row, dict), f"{label}: object")
        exact(
            row,
            {
                "case",
                "receipt",
                "outcome",
                "indeterminatePreserved",
                "stateResetAttempted",
            },
            label,
        )
        name = text(row["case"], f"{label}.case")
        need(name in FAULTS and name not in seen_faults, f"{label}.case")
        seen_faults.add(name)
        outcome = text(row["outcome"], f"{label}.outcome")
        need(outcome in FAULT_OUTCOMES, f"{label}.outcome")
        if name == "restart_with_older_local_snapshot":
            need(outcome == "rollback_rejected", f"{label}: old snapshot accepted")
        if name in UNCERTAIN_FAULTS:
            need(outcome != "reopen_succeeds", f"{label}: uncertainty became success")
        must_true(row["indeterminatePreserved"], f"{label}.indeterminatePreserved")
        must_false(row["stateResetAttempted"], f"{label}.stateResetAttempted")
        add(
            row["receipt"],
            f"{label}.receipt",
            "capacity_fault_result",
            {
                "case": name,
                "outcome": outcome,
                "indeterminatePreserved": True,
                "stateResetAttempted": False,
            },
        )
    need(seen_faults == FAULTS, "capacity.faultResults: incomplete")

    reserve = capacity["reserveAlert"]
    need(isinstance(reserve, dict), "capacity.reserveAlert: object")
    exact(
        reserve,
        {"receipt", "hardLimit", "reserveThreshold", "observedRemaining", "triggered"},
        "capacity.reserveAlert",
    )
    hard = positive(reserve["hardLimit"], "capacity.reserveAlert.hardLimit")
    threshold = positive(
        reserve["reserveThreshold"], "capacity.reserveAlert.reserveThreshold"
    )
    remaining = nonnegative(
        reserve["observedRemaining"], "capacity.reserveAlert.observedRemaining"
    )
    need(
        threshold < hard and 0 < remaining <= threshold,
        "capacity.reserveAlert: not demonstrated before hard limit",
    )
    must_true(reserve["triggered"], "capacity.reserveAlert.triggered")
    add(
        reserve["receipt"],
        "capacity.reserveAlert.receipt",
        "capacity_reserve_alert",
        {
            "hardLimit": hard,
            "reserveThreshold": threshold,
            "observedRemaining": remaining,
            "triggered": True,
        },
    )
    add(
        capacity["qualificationReceipt"],
        "capacity.qualificationReceipt",
        "capacity_qualification",
        {
            "points": sorted(POINTS),
            "operations": sorted(OPERATIONS),
            "measurementCount": len(measurements),
            "faultCases": sorted(FAULTS),
            "faultResultCount": len(fault_rows),
            "reserveAlertDemonstrated": True,
        },
    )

    acceptance = document["operatorAcceptance"]
    need(isinstance(acceptance, dict), "operatorAcceptance: object")
    exact(
        acceptance,
        {
            "reviewerId",
            "receipt",
            "acceptedCandidateCommit",
            "acceptedCandidateTree",
            "accepted",
        },
        "operatorAcceptance",
    )
    reviewer = text(acceptance["reviewerId"], "operatorAcceptance.reviewerId")
    accepted_commit = git_sha(
        acceptance["acceptedCandidateCommit"],
        "operatorAcceptance.acceptedCandidateCommit",
    )
    accepted_tree = git_sha(
        acceptance["acceptedCandidateTree"], "operatorAcceptance.acceptedCandidateTree"
    )
    need(
        accepted_commit == commit and accepted_tree == tree,
        "operatorAcceptance: candidate mismatch",
    )
    must_true(acceptance["accepted"], "operatorAcceptance.accepted")
    add(
        acceptance["receipt"],
        "operatorAcceptance.receipt",
        "operator_acceptance",
        {
            "reviewerId": reviewer,
            "acceptedCandidateCommit": commit,
            "acceptedCandidateTree": tree,
            "accepted": True,
        },
    )
    return specs


def validate(
    document: dict[str, Any],
    root: Path,
    expected_commit: str | None,
    expected_tree: str | None,
) -> None:
    exact(
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
    need(
        document["schema"] == SCHEMA
        and type(document["schemaVersion"]) is int
        and document["schemaVersion"] == SCHEMA_VERSION,
        "bundle: schema",
    )
    candidate = document["candidate"]
    need(isinstance(candidate, dict), "candidate: object")
    exact(candidate, {"commit", "tree"}, "candidate")
    commit = git_sha(candidate["commit"], "candidate.commit")
    tree = git_sha(candidate["tree"], "candidate.tree")
    if expected_commit is not None:
        need(commit == expected_commit, "candidate.commit: expected exact source")
    if expected_tree is not None:
        need(tree == expected_tree, "candidate.tree: expected exact tree")
    specs = claim_specs(document, commit, tree)
    artifacts = artifact_index(root, document["artifacts"])
    used: set[str] = set()
    for spec in specs:
        need(spec.path in artifacts, f"{spec.label}: missing from artifacts")
        need(spec.path not in used, f"{spec.label}: receipt reused: {spec.path}")
        used.add(spec.path)
        receipt = parse_json(artifacts[spec.path], spec.path)
        exact(
            receipt,
            {
                "schema",
                "schemaVersion",
                "candidate",
                "kind",
                "producerId",
                "observedAtUnixMs",
                "synthetic",
                "data",
            },
            f"{spec.label}.envelope",
        )
        need(
            receipt["schema"] == RECEIPT_SCHEMA
            and type(receipt["schemaVersion"]) is int
            and receipt["schemaVersion"] == RECEIPT_SCHEMA_VERSION,
            f"{spec.label}: receipt schema",
        )
        receipt_candidate = receipt["candidate"]
        need(isinstance(receipt_candidate, dict), f"{spec.label}.candidate: object")
        exact(receipt_candidate, {"commit", "tree"}, f"{spec.label}.candidate")
        need(
            git_sha(receipt_candidate["commit"], f"{spec.label}.candidate.commit")
            == commit,
            f"{spec.label}: receipt commit mismatch",
        )
        need(
            git_sha(receipt_candidate["tree"], f"{spec.label}.candidate.tree") == tree,
            f"{spec.label}: receipt tree mismatch",
        )
        need(
            text(receipt["kind"], f"{spec.label}.kind") == spec.kind,
            f"{spec.label}: receipt kind",
        )
        text(receipt["producerId"], f"{spec.label}.producerId")
        positive(receipt["observedAtUnixMs"], f"{spec.label}.observedAtUnixMs")
        must_false(receipt["synthetic"], f"{spec.label}.synthetic")
        need(
            json.dumps(
                canonical(receipt["data"], f"{spec.label}.data"),
                sort_keys=True,
                allow_nan=False,
            )
            == json.dumps(spec.data, sort_keys=True, allow_nan=False),
            f"{spec.label}: receipt content/type mismatch",
        )


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
    commit, tree = "a" * 40, "b" * 40
    nodes = ["node-a", "node-b"]
    measurements = [
        {
            "point": point,
            "operation": operation,
            "receipt": f"measure-{point}-{operation}.json",
            "sampleCount": 1000,
            "p50Ms": 10,
            "p95Ms": 20,
            "p99Ms": 30,
            "latencyBudgetMs": 40,
            "bytesWritten": 4096,
            "fsyncP99Ms": 5,
            "peakRssBytes": 1048576,
        }
        for point in sorted(POINTS)
        for operation in sorted(OPERATIONS)
    ]
    fault_rows = []
    for name in sorted(FAULTS):
        outcome = (
            "rollback_rejected"
            if name == "restart_with_older_local_snapshot"
            else ("fenced" if name in UNCERTAIN_FAULTS else "reopen_succeeds")
        )
        fault_rows.append(
            {
                "case": name,
                "receipt": f"fault-{name}.json",
                "outcome": outcome,
                "indeterminatePreserved": True,
                "stateResetAttempted": False,
            }
        )
    document: dict[str, Any] = {
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
            "enrolledNodes": nodes,
            "feedLifetimeMs": 5000,
            "convergenceSlaMs": 1000,
            "scenarios": [
                {
                    "name": name,
                    "receipt": f"{name}.json",
                    "maxDeliveryMs": 100,
                    "maxAckMs": 200,
                    "deliveredNodeCount": 2,
                    "acknowledgedNodeCount": 2,
                }
                for name in sorted(SCENARIOS)
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
            for role in sorted(KEY_ROLES)
        ],
        "capacity": {
            "qualificationReceipt": "capacity.json",
            "measurements": measurements,
            "faultResults": fault_rows,
            "reserveAlert": {
                "receipt": "reserve-alert.json",
                "hardLimit": 16384,
                "reserveThreshold": 1024,
                "observedRemaining": 1000,
                "triggered": True,
            },
        },
        "operatorAcceptance": {
            "reviewerId": "independent-reviewer",
            "receipt": "operator.json",
            "acceptedCandidateCommit": commit,
            "acceptedCandidateTree": tree,
            "accepted": True,
        },
        "artifacts": [],
    }
    artifacts = []
    for spec in claim_specs(document, commit, tree):
        receipt = {
            "schema": RECEIPT_SCHEMA,
            "schemaVersion": RECEIPT_SCHEMA_VERSION,
            "candidate": {"commit": commit, "tree": tree},
            "kind": spec.kind,
            "producerId": "fixture-independent-producer",
            "observedAtUnixMs": 1900000000000,
            "synthetic": False,
            "data": spec.data,
        }
        path = root / spec.path
        write_json(path, receipt)
        artifacts.append(
            {"path": spec.path, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        )
    document["artifacts"] = artifacts
    return document


def mutate_receipt(
    document: dict[str, Any],
    root: Path,
    name: str,
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    value = load_json(root / name)
    mutate(value)
    write_json(root / name, value)
    for row in document["artifacts"]:
        if row["path"] == name:
            row["sha256"] = hashlib.sha256((root / name).read_bytes()).hexdigest()
            return
    raise AssertionError(name)


def self_test() -> int:
    cases: list[tuple[str, Callable[[dict[str, Any], Path], None]]] = [
        (
            "boolean_receipt_schema",
            lambda d, r: mutate_receipt(
                d, r, "clock.json", lambda x: x.__setitem__("schemaVersion", True)
            ),
        ),
        (
            "numeric_boolean_receipt",
            lambda d, r: mutate_receipt(
                d, r, "clock.json", lambda x: x["data"].__setitem__("failClosed", 1)
            ),
        ),
        (
            "float_integer_receipt",
            lambda d, r: mutate_receipt(
                d,
                r,
                "clock.json",
                lambda x: x["data"].__setitem__("maxClockUncertaintyMs", 100.0),
            ),
        ),
        (
            "late_reserve_alert",
            lambda d, _: d["capacity"]["reserveAlert"].__setitem__(
                "observedRemaining", 0
            ),
        ),
        (
            "clock_not_fail_closed",
            lambda d, _: d["trustedTime"].__setitem__("failClosed", False),
        ),
        (
            "rollback_not_rejected",
            lambda d, _: d["antiRollback"].__setitem__(
                "restoredSnapshotRejected", False
            ),
        ),
        (
            "duplicate_node",
            lambda d, _: d["revocationDistribution"]["enrolledNodes"].append("node-a"),
        ),
        (
            "missing_scenario",
            lambda d, _: d["revocationDistribution"].__setitem__(
                "scenarios", d["revocationDistribution"]["scenarios"][:-1]
            ),
        ),
        (
            "key_exposure",
            lambda d, _: d["keyCustody"][0].__setitem__(
                "applicationPrivateKeyExposure", "general_application"
            ),
        ),
        (
            "ack_exceeds_sla",
            lambda d, _: d["revocationDistribution"]["scenarios"][0].__setitem__(
                "maxAckMs", 1001
            ),
        ),
        (
            "ack_before_delivery",
            lambda d, _: (
                d["revocationDistribution"]["scenarios"][0].__setitem__(
                    "maxDeliveryMs", 300
                ),
                d["revocationDistribution"]["scenarios"][0].__setitem__(
                    "maxAckMs", 200
                ),
            ),
        ),
        (
            "missing_measurement",
            lambda d, _: d["capacity"].__setitem__(
                "measurements", d["capacity"]["measurements"][:-1]
            ),
        ),
        (
            "p99_exceeds_budget",
            lambda d, _: d["capacity"]["measurements"][0].__setitem__("p99Ms", 41),
        ),
        (
            "lost_indeterminate",
            lambda d, _: d["capacity"]["faultResults"][0].__setitem__(
                "indeterminatePreserved", False
            ),
        ),
        (
            "reserve_not_exercised",
            lambda d, _: d["capacity"]["reserveAlert"].__setitem__(
                "observedRemaining", 2000
            ),
        ),
        (
            "operator_tree_drift",
            lambda d, _: d["operatorAcceptance"].__setitem__(
                "acceptedCandidateTree", "c" * 40
            ),
        ),
        (
            "synthetic_receipt",
            lambda d, r: mutate_receipt(
                d, r, "clock.json", lambda x: x.__setitem__("synthetic", True)
            ),
        ),
        (
            "receipt_candidate_drift",
            lambda d, r: mutate_receipt(
                d,
                r,
                "frontier.json",
                lambda x: x["candidate"].__setitem__("tree", "c" * 40),
            ),
        ),
        (
            "receipt_kind_drift",
            lambda d, r: mutate_receipt(
                d,
                r,
                "normal.json",
                lambda x: x.__setitem__(
                    "kind", "revocation_distribution_qualification"
                ),
            ),
        ),
        (
            "missing_measurement_content",
            lambda d, r: mutate_receipt(
                d,
                r,
                d["capacity"]["measurements"][0]["receipt"],
                lambda x: x.__setitem__("data", {}),
            ),
        ),
        (
            "measurement_content_mismatch",
            lambda d, r: mutate_receipt(
                d,
                r,
                d["capacity"]["measurements"][0]["receipt"],
                lambda x: x["data"].__setitem__("p99Ms", 29),
            ),
        ),
        (
            "receipt_reuse",
            lambda d, _: d["capacity"]["measurements"][1].__setitem__(
                "receipt", d["capacity"]["measurements"][0]["receipt"]
            ),
        ),
        (
            "artifact_substitution",
            lambda d, _: d["artifacts"][0].__setitem__("sha256", "d" * 64),
        ),
    ]
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        valid_root = root / "valid"
        valid_root.mkdir()
        valid = fixture(valid_root)
        validate(valid, valid_root, "a" * 40, "b" * 40)
        for name, mutate in cases:
            case_root = root / name
            case_root.mkdir()
            document = fixture(case_root)
            mutate(document, case_root)
            try:
                validate(document, case_root, "a" * 40, "b" * 40)
            except Invalid:
                continue
            raise Invalid(f"self-test accepted hostile case: {name}")
    print(
        json.dumps(
            {
                "status": "PASS_KERNEL_AUTHORITY_PRODUCTION_EVIDENCE_SELF_TEST",
                "receiptContentValidated": True,
                "negativeCases": len(cases),
                "activationGranted": False,
            },
            sort_keys=True,
        )
    )
    return 0


def verify(path: Path, expected_sha: str) -> int:
    path = path.resolve()
    need(path.is_file(), "evidence path must be a file")
    commit, tree = current_identity(expected_sha)
    validate(load_json(path), path.parent, commit, tree)
    print(
        json.dumps(
            {
                "status": "PASS_KERNEL_AUTHORITY_PRODUCTION_EVIDENCE_ADMISSION",
                "candidateCommit": commit,
                "candidateTree": tree,
                "evidenceAdmitted": True,
                "receiptContentValidated": True,
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
    return (
        self_test()
        if args.command == "self-test"
        else verify(args.evidence, args.expected_sha)
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Invalid as exc:
        raise SystemExit(f"FAIL_KERNEL_AUTHORITY_PRODUCTION_EVIDENCE: {exc}") from exc
