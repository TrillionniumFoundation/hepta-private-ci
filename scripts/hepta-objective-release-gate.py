#!/usr/bin/env python3
"""Fail-closed release gate for objective.compiler qualification receipts.

The source tree may describe release mechanics, but it cannot self-assert target
host qualification, independent acceptance, canary success, promotion, rollback
readiness or release authority. Those facts arrive as immutable, digest-linked
receipts bound to one exact candidate commit/tree and this policy.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "docs/modules/objective.compiler/CURRENT_STATE.json"
POLICY_PATH = ROOT / "docs/modules/objective.compiler/RELEASE_POLICY.json"
RECEIPT_SCHEMA = "hepta.objective-release-receipt.v1"
READY_SCHEMA = "hepta.objective-release-readiness.v1"
HEX40 = re.compile(r"[0-9a-f]{40}")
HEX64 = re.compile(r"[0-9a-f]{64}")


class GateError(ValueError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    def unique(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise GateError(f"duplicate JSON key in {path}: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    except (OSError, json.JSONDecodeError) as error:
        raise GateError(f"cannot read {path}: {error}") from error
    if not isinstance(value, dict):
        raise GateError(f"{path} must contain a JSON object")
    return value


def git(*args: str) -> str:
    result = subprocess.run(
        ("git", *args),
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def require_hex(value: Any, pattern: re.Pattern[str], label: str) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise GateError(f"{label} must be lowercase hexadecimal")
    return value


def parse_timestamp(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise GateError(f"{label} must be an RFC3339 UTC timestamp")
    try:
        dt.datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise GateError(f"{label} is not a valid timestamp") from error
    return value


def validate_policy(policy: dict[str, Any]) -> list[dict[str, Any]]:
    expected = {
        "schema",
        "schemaVersion",
        "module",
        "receiptSchema",
        "receiptKinds",
        "distinctIssuers",
        "sourceTruthBeforeRelease",
        "releaseTruthAfterAllReceipts",
    }
    if set(policy) != expected:
        raise GateError("release policy top-level fields drifted")
    if (
        policy["schema"] != "hepta.objective-release-policy.v1"
        or policy["schemaVersion"] != 1
        or policy["module"] != "objective.compiler"
        or policy["receiptSchema"] != RECEIPT_SCHEMA
    ):
        raise GateError("invalid release policy identity")
    kinds = policy["receiptKinds"]
    if not isinstance(kinds, list) or not kinds:
        raise GateError("receiptKinds must be a non-empty list")
    seen: set[str] = set()
    ordered: list[dict[str, Any]] = []
    for row in kinds:
        if not isinstance(row, dict) or set(row) != {
            "kind",
            "fileName",
            "dependsOn",
            "requiredPayloadFields",
        }:
            raise GateError("invalid receiptKinds row")
        kind = row["kind"]
        if (
            not isinstance(kind, str)
            or re.fullmatch(r"[a-z][a-z0-9_]*", kind) is None
            or kind in seen
        ):
            raise GateError(f"invalid or duplicate receipt kind: {kind!r}")
        filename = row["fileName"]
        if (
            not isinstance(filename, str)
            or Path(filename).name != filename
            or not filename.endswith(".json")
        ):
            raise GateError(f"invalid receipt filename for {kind}")
        dependencies = row["dependsOn"]
        if (
            not isinstance(dependencies, list)
            or any(not isinstance(item, str) or item not in seen for item in dependencies)
            or len(set(dependencies)) != len(dependencies)
        ):
            raise GateError(f"dependencies for {kind} must name earlier unique receipts")
        payload_fields = row["requiredPayloadFields"]
        if (
            not isinstance(payload_fields, list)
            or not payload_fields
            or any(
                not isinstance(item, str)
                or re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", item) is None
                for item in payload_fields
            )
            or len(set(payload_fields)) != len(payload_fields)
        ):
            raise GateError(f"invalid payload field inventory for {kind}")
        seen.add(kind)
        ordered.append(row)
    pairs = policy["distinctIssuers"]
    if not isinstance(pairs, list):
        raise GateError("distinctIssuers must be a list")
    for pair in pairs:
        if (
            not isinstance(pair, list)
            or len(pair) != 2
            or pair[0] not in seen
            or pair[1] not in seen
            or pair[0] == pair[1]
        ):
            raise GateError("invalid distinct issuer pair")
    expected_false = {
        "productionImplementation": False,
        "accepted": False,
        "activated": False,
        "released": False,
    }
    expected_true = {key: True for key in expected_false}
    if policy["sourceTruthBeforeRelease"] != expected_false:
        raise GateError("sourceTruthBeforeRelease must remain fail-closed")
    if policy["releaseTruthAfterAllReceipts"] != expected_true:
        raise GateError("releaseTruthAfterAllReceipts must require the complete gate")
    return ordered


def validate_state(state: dict[str, Any], policy: dict[str, Any]) -> None:
    if (
        state.get("schema") != "hepta.objective-compiler-current-state.v1"
        or state.get("schemaVersion") != 1
        or state.get("module") != "objective.compiler"
    ):
        raise GateError("invalid objective.compiler current-state identity")
    truth = state.get("truth")
    if not isinstance(truth, dict):
        raise GateError("current-state truth must be an object")
    allowed = {
        tuple(sorted(policy["sourceTruthBeforeRelease"].items())),
        tuple(sorted(policy["releaseTruthAfterAllReceipts"].items())),
    }
    if tuple(sorted(truth.items())) not in allowed:
        raise GateError("current-state truth is neither pre-release nor fully released")


def validate_payload(kind: str, payload: dict[str, Any]) -> None:
    def boolean(name: str, expected: bool = True) -> None:
        if payload.get(name) is not expected:
            raise GateError(f"{kind}.payload.{name} must be {expected}")

    def positive(name: str) -> None:
        if type(payload.get(name)) is not int or payload[name] <= 0:
            raise GateError(f"{kind}.payload.{name} must be a positive integer")

    if kind == "exact_head_qualification":
        checks = payload.get("checkRuns")
        if not isinstance(checks, list) or not checks:
            raise GateError("exact-head receipt requires checkRuns")
        for check in checks:
            if (
                not isinstance(check, dict)
                or set(check) != {"name", "runId", "conclusion"}
                or not isinstance(check["name"], str)
                or type(check["runId"]) is not int
                or check["runId"] <= 0
                or check["conclusion"] != "success"
            ):
                raise GateError("exact-head check run is not a successful immutable identity")
        require_hex(payload.get("sourceMapDigest"), HEX64, "sourceMapDigest")
        require_hex(payload.get("currentStateDigest"), HEX64, "currentStateDigest")
    elif kind == "synthetic_merge_qualification":
        require_hex(payload.get("baseCommit"), HEX40, "baseCommit")
        require_hex(payload.get("mergeCommit"), HEX40, "mergeCommit")
        require_hex(payload.get("mergeTree"), HEX40, "mergeTree")
        positive("checkRunId")
        boolean("allChecksPassed")
    elif kind == "target_host_qualification":
        if not isinstance(payload.get("hostProfileId"), str) or not payload["hostProfileId"]:
            raise GateError("target-host receipt requires hostProfileId")
        require_hex(payload.get("measurementDigest"), HEX64, "measurementDigest")
        require_hex(
            payload.get("storageQualificationDigest"),
            HEX64,
            "storageQualificationDigest",
        )
        boolean("worstCase257OracleCallsMeasured")
        boolean("resourceBudgetsAccepted")
        boolean("storageDurabilityAccepted")
    elif kind == "independent_review":
        if not isinstance(payload.get("reviewerRole"), str) or not payload["reviewerRole"]:
            raise GateError("independent review requires reviewerRole")
        require_hex(payload.get("reviewScopeDigest"), HEX64, "reviewScopeDigest")
        boolean("independent")
        boolean("noUnresolvedBlockingFindings")
    elif kind == "canary":
        if not isinstance(payload.get("environment"), str) or not payload["environment"]:
            raise GateError("canary requires environment")
        parse_timestamp(payload.get("windowStartedAt"), "windowStartedAt")
        parse_timestamp(payload.get("windowEndedAt"), "windowEndedAt")
        positive("observedRequests")
        if payload.get("hardConstraintViolations") != 0:
            raise GateError("canary hardConstraintViolations must be zero")
        require_hex(payload.get("rollbackDrillDigest"), HEX64, "rollbackDrillDigest")
        boolean("latencyBudgetsSatisfied")
        boolean("errorBudgetsSatisfied")
    elif kind == "promotion":
        for name in ("fromEnvironment", "toEnvironment", "approvedByRole"):
            if not isinstance(payload.get(name), str) or not payload[name]:
                raise GateError(f"promotion requires {name}")
        require_hex(payload.get("canaryReceiptDigest"), HEX64, "canaryReceiptDigest")
        boolean("approved")
    elif kind == "rollback_authority":
        if not isinstance(payload.get("authorityRole"), str) or not payload["authorityRole"]:
            raise GateError("rollback authority requires authorityRole")
        require_hex(payload.get("rollbackTargetCommit"), HEX40, "rollbackTargetCommit")
        require_hex(payload.get("procedureDigest"), HEX64, "procedureDigest")
        require_hex(payload.get("drillReceiptDigest"), HEX64, "drillReceiptDigest")
        boolean("ready")
    elif kind == "release_authority":
        for name in ("authorityRole", "targetEnvironment", "approvalId"):
            if not isinstance(payload.get(name), str) or not payload[name]:
                raise GateError(f"release authority requires {name}")
        require_hex(payload.get("promotionReceiptDigest"), HEX64, "promotionReceiptDigest")
        require_hex(
            payload.get("rollbackAuthorityReceiptDigest"),
            HEX64,
            "rollbackAuthorityReceiptDigest",
        )
        boolean("approved")
    else:
        raise GateError(f"unsupported receipt kind: {kind}")


def validate_receipts(
    policy: dict[str, Any],
    receipt_dir: Path,
    candidate_commit: str,
    candidate_tree: str,
) -> tuple[dict[str, dict[str, Any]], str]:
    kinds = validate_policy(policy)
    require_hex(candidate_commit, HEX40, "candidate commit")
    require_hex(candidate_tree, HEX40, "candidate tree")
    policy_digest = sha256_value(policy)
    receipts: dict[str, dict[str, Any]] = {}
    issuers: dict[str, str] = {}
    for row in kinds:
        kind = row["kind"]
        receipt = load_json(receipt_dir / row["fileName"])
        expected_keys = {
            "schema",
            "schemaVersion",
            "module",
            "kind",
            "candidateCommit",
            "candidateTree",
            "releasePolicyDigest",
            "issuer",
            "issuedAt",
            "evidenceDigest",
            "accepted",
            "dependencies",
            "payload",
            "receiptDigest",
        }
        if set(receipt) != expected_keys:
            raise GateError(f"{kind} receipt top-level fields drifted")
        if (
            receipt["schema"] != RECEIPT_SCHEMA
            or receipt["schemaVersion"] != 1
            or receipt["module"] != "objective.compiler"
            or receipt["kind"] != kind
            or receipt["candidateCommit"] != candidate_commit
            or receipt["candidateTree"] != candidate_tree
            or receipt["releasePolicyDigest"] != policy_digest
            or receipt["accepted"] is not True
        ):
            raise GateError(f"{kind} receipt identity or acceptance mismatch")
        issuer = receipt["issuer"]
        if not isinstance(issuer, str) or not issuer.strip():
            raise GateError(f"{kind} receipt issuer is missing")
        parse_timestamp(receipt["issuedAt"], f"{kind}.issuedAt")
        require_hex(receipt["evidenceDigest"], HEX64, f"{kind}.evidenceDigest")
        payload = receipt["payload"]
        if not isinstance(payload, dict):
            raise GateError(f"{kind} payload must be an object")
        if set(payload) != set(row["requiredPayloadFields"]):
            raise GateError(f"{kind} payload fields drifted")
        validate_payload(kind, payload)
        dependencies = receipt["dependencies"]
        expected_dependencies = {
            dependency: receipts[dependency]["receiptDigest"]
            for dependency in row["dependsOn"]
        }
        if dependencies != expected_dependencies:
            raise GateError(f"{kind} dependency chain mismatch")
        supplied_digest = require_hex(
            receipt["receiptDigest"], HEX64, f"{kind}.receiptDigest"
        )
        unsigned = dict(receipt)
        del unsigned["receiptDigest"]
        if sha256_value(unsigned) != supplied_digest:
            raise GateError(f"{kind} receipt digest mismatch")
        receipts[kind] = receipt
        issuers[kind] = issuer
    for left, right in policy["distinctIssuers"]:
        if issuers[left] == issuers[right]:
            raise GateError(f"{left} and {right} require distinct issuers")
    promotion = receipts["promotion"]
    canary = receipts["canary"]
    if promotion["payload"]["canaryReceiptDigest"] != canary["receiptDigest"]:
        raise GateError("promotion does not bind the admitted canary receipt")
    release = receipts["release_authority"]
    if release["payload"]["promotionReceiptDigest"] != promotion["receiptDigest"]:
        raise GateError("release authority does not bind promotion")
    rollback = receipts["rollback_authority"]
    if (
        release["payload"]["rollbackAuthorityReceiptDigest"]
        != rollback["receiptDigest"]
    ):
        raise GateError("release authority does not bind rollback authority")
    return receipts, policy_digest


def source_verify(state: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    validate_policy(policy)
    validate_state(state, policy)
    truth = state["truth"]
    if truth != policy["sourceTruthBeforeRelease"]:
        raise GateError(
            "released truth cannot be committed by source CI; use the protected release gate"
        )
    return {
        "schema": READY_SCHEMA,
        "module": "objective.compiler",
        "sourceTruthFailClosed": True,
        "releasePolicyDigest": sha256_value(policy),
        "releaseGranted": False,
    }


def release_verify(
    state: dict[str, Any],
    policy: dict[str, Any],
    receipt_dir: Path,
    candidate_commit: str,
    candidate_tree: str,
) -> dict[str, Any]:
    validate_state(state, policy)
    receipts, policy_digest = validate_receipts(
        policy, receipt_dir, candidate_commit, candidate_tree
    )
    return {
        "schema": READY_SCHEMA,
        "schemaVersion": 1,
        "module": "objective.compiler",
        "candidateCommit": candidate_commit,
        "candidateTree": candidate_tree,
        "releasePolicyDigest": policy_digest,
        "receiptDigests": {
            kind: receipt["receiptDigest"] for kind, receipt in receipts.items()
        },
        "releaseTruth": policy["releaseTruthAfterAllReceipts"],
        "releaseGranted": True,
    }


def resolve_candidate(args: argparse.Namespace) -> tuple[str, str]:
    commit = args.expected_sha or git("rev-parse", "HEAD")
    tree = args.expected_tree or git("rev-parse", f"{commit}^{{tree}}")
    require_hex(commit, HEX40, "expected SHA")
    require_hex(tree, HEX40, "expected tree")
    if args.expected_sha and git("rev-parse", "HEAD") != commit:
        raise GateError("checkout does not match expected candidate SHA")
    if git("rev-parse", f"{commit}^{{tree}}") != tree:
        raise GateError("candidate tree does not match expected tree")
    if git("status", "--porcelain"):
        raise GateError("release verification requires a clean checkout")
    return commit, tree


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify-source", "verify-release"))
    parser.add_argument("--state", type=Path, default=STATE_PATH)
    parser.add_argument("--policy", type=Path, default=POLICY_PATH)
    parser.add_argument("--receipts", type=Path)
    parser.add_argument("--expected-sha")
    parser.add_argument("--expected-tree")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        state = load_json(args.state)
        policy = load_json(args.policy)
        if args.command == "verify-source":
            result = source_verify(state, policy)
        else:
            if args.receipts is None:
                parser.error("verify-release requires --receipts")
            commit, tree = resolve_candidate(args)
            result = release_verify(state, policy, args.receipts, commit, tree)
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (GateError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"FAIL_HEPTA_OBJECTIVE_RELEASE_GATE: {error}") from error


if __name__ == "__main__":
    raise SystemExit(main())
