#!/usr/bin/env python3
"""Validate a signed context.compiler external-acceptance receipt payload.

Detached signature verification is deliberately performed by the protected
workflow with its environment-owned public key. This module validates the
strict receipt structure, immutable Git/host bindings, expiries, evidence set,
failpoint coverage, approvals, and canonical receipt digest. It never mutates
canonical module state or grants deployment authority.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = ROOT / "qualification/context-compiler/FAILPOINT_MATRIX.json"
MAX_RECEIPT_BYTES = 2 * 1024 * 1024
OID = re.compile(r"[0-9a-f]{40}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
BOUNDED_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}\Z")
FORBIDDEN_KEY_PARTS = (
    "secret",
    "credential",
    "privatekey",
    "private_key",
    "access_token",
    "api_key",
)

EVIDENCE_BASE = (
    "sourceHeadQualification",
    "syntheticMergeQualification",
    "authoritySigner",
    "tokenizerCustody",
    "distributedLease",
    "appendOnlyJournal",
    "providerTerminalAttestation",
    "filesystemRestore",
    "multiHostDuplicateDenial",
    "providerE2E",
    "targetHostProfile",
    "failureInjection",
    "independentSecurityReview",
)
EVIDENCE_BY_MODE = {
    "independent": EVIDENCE_BASE,
    "activation": (*EVIDENCE_BASE, "canaryRollback"),
    "release": (*EVIDENCE_BASE, "canaryRollback"),
}
TOP_LEVEL_KEYS = {
    "schema",
    "mode",
    "identities",
    "environment",
    "evidence",
    "failpoints",
    "approvals",
    "independentAcceptance",
    "activationApproved",
    "releaseApproved",
    "receiptSha256",
}
IDENTITY_KEYS = {
    "sourceCommit",
    "sourceTree",
    "baseCommit",
    "mergeCommit",
    "mergeTree",
}
ENVIRONMENT_KEYS = {
    "environmentId",
    "runnerIdentity",
    "runnerImageDigest",
    "hostImageDigest",
    "kernelIdentity",
    "filesystemIdentity",
    "providerTenant",
    "createdAt",
    "expiresAt",
}
EVIDENCE_KEYS = {
    "status",
    "artifactSha256",
    "issuer",
    "issuedAt",
    "expiresAt",
    "sourceCommit",
    "sourceTree",
    "mergeCommit",
    "mergeTree",
}
FAILPOINT_RESULT_KEYS = {"status", "observedState", "artifactSha256"}
APPROVAL_KEYS = {
    "status",
    "approverId",
    "approvalSha256",
    "issuedAt",
    "sourceCommit",
    "mergeTree",
}
APPROVAL_NAMES = {"security", "operator", "release"}


class AcceptanceError(ValueError):
    pass


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise AcceptanceError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def canonical_sha256(value: dict[str, Any]) -> str:
    unsigned = dict(value)
    unsigned.pop("receiptSha256", None)
    payload = json.dumps(
        unsigned,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def parse_time(value: Any, field: str) -> dt.datetime:
    if not isinstance(value, str) or len(value) > 64:
        raise AcceptanceError(f"{field} is not a bounded timestamp")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError as error:
        raise AcceptanceError(f"{field} is not ISO-8601") from error
    if parsed.tzinfo is None:
        raise AcceptanceError(f"{field} must include a timezone")
    return parsed.astimezone(dt.timezone.utc)


def require_exact_keys(
    value: Any,
    expected: set[str],
    field: str,
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        actual = sorted(value) if isinstance(value, dict) else type(value).__name__
        raise AcceptanceError(f"{field} keys mismatch: {actual}")
    return value


def require_oid(value: Any, field: str) -> str:
    if not isinstance(value, str) or not OID.fullmatch(value):
        raise AcceptanceError(f"{field} must be a full Git object id")
    return value


def require_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise AcceptanceError(f"{field} must be a lowercase SHA-256 digest")
    return value


def require_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not BOUNDED_ID.fullmatch(value):
        raise AcceptanceError(f"{field} must be a bounded stable identity")
    return value


def reject_sensitive_keys(value: Any, path: str = "receipt") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = key.lower()
            if any(part in lowered for part in FORBIDDEN_KEY_PARTS):
                raise AcceptanceError(f"sensitive key is forbidden at {path}.{key}")
            reject_sensitive_keys(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            reject_sensitive_keys(item, f"{path}[{index}]")
    elif isinstance(value, str) and len(value) > 4096:
        raise AcceptanceError(f"unbounded string at {path}")


def load_matrix(path: Path = MATRIX_PATH) -> dict[str, set[str]]:
    value = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=unique_object,
    )
    if value.get("schema") != "hepta.context-compiler.failpoint-matrix.v1":
        raise AcceptanceError("unsupported failpoint matrix schema")
    points = value.get("points")
    if not isinstance(points, list) or not points:
        raise AcceptanceError("failpoint matrix is empty")
    result: dict[str, set[str]] = {}
    for point in points:
        if not isinstance(point, dict) or set(point) != {
            "id",
            "phase",
            "allowedObservedStates",
        }:
            raise AcceptanceError("invalid failpoint matrix entry")
        point_id = require_id(point["id"], "failpoint id")
        require_id(point["phase"], f"{point_id}.phase")
        states = point["allowedObservedStates"]
        if (
            not isinstance(states, list)
            or not states
            or any(not isinstance(item, str) for item in states)
        ):
            raise AcceptanceError(f"{point_id} has invalid allowed states")
        if point_id in result:
            raise AcceptanceError(f"duplicate failpoint id: {point_id}")
        result[point_id] = set(states)
    return result


def validate_approval(
    name: str,
    value: Any,
    identities: dict[str, Any],
    required: bool,
) -> None:
    if value is None:
        if required:
            raise AcceptanceError(f"{name} approval is required")
        return
    approval = require_exact_keys(value, APPROVAL_KEYS, f"approvals.{name}")
    if approval["status"] != "approved":
        raise AcceptanceError(f"{name} approval is not approved")
    require_id(approval["approverId"], f"approvals.{name}.approverId")
    require_sha256(
        approval["approvalSha256"],
        f"approvals.{name}.approvalSha256",
    )
    parse_time(approval["issuedAt"], f"approvals.{name}.issuedAt")
    if (
        approval["sourceCommit"] != identities["sourceCommit"]
        or approval["mergeTree"] != identities["mergeTree"]
    ):
        raise AcceptanceError(f"{name} approval identity drift")


def validate_receipt(
    receipt: dict[str, Any],
    *,
    mode: str,
    expected_source: str,
    expected_source_tree: str,
    expected_base: str,
    expected_merge: str,
    expected_merge_tree: str,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    require_exact_keys(receipt, TOP_LEVEL_KEYS, "receipt")
    reject_sensitive_keys(receipt)
    if receipt["schema"] != "hepta.context-compiler.external-acceptance.v1":
        raise AcceptanceError("unsupported acceptance receipt schema")
    if mode not in EVIDENCE_BY_MODE or receipt["mode"] != mode:
        raise AcceptanceError("acceptance mode mismatch")
    require_sha256(receipt["receiptSha256"], "receiptSha256")
    if receipt["receiptSha256"] != canonical_sha256(receipt):
        raise AcceptanceError("receipt canonical digest mismatch")

    identities = require_exact_keys(
        receipt["identities"],
        IDENTITY_KEYS,
        "identities",
    )
    expected = {
        "sourceCommit": require_oid(expected_source, "expected source"),
        "sourceTree": require_oid(expected_source_tree, "expected source tree"),
        "baseCommit": require_oid(expected_base, "expected base"),
        "mergeCommit": require_oid(expected_merge, "expected merge"),
        "mergeTree": require_oid(expected_merge_tree, "expected merge tree"),
    }
    for field, expected_value in expected.items():
        require_oid(identities[field], f"identities.{field}")
        if identities[field] != expected_value:
            raise AcceptanceError(f"immutable identity mismatch: {field}")

    environment = require_exact_keys(
        receipt["environment"],
        ENVIRONMENT_KEYS,
        "environment",
    )
    for field in (
        "environmentId",
        "runnerIdentity",
        "kernelIdentity",
        "filesystemIdentity",
        "providerTenant",
    ):
        require_id(environment[field], f"environment.{field}")
    require_sha256(
        environment["runnerImageDigest"],
        "environment.runnerImageDigest",
    )
    require_sha256(
        environment["hostImageDigest"],
        "environment.hostImageDigest",
    )
    created = parse_time(environment["createdAt"], "environment.createdAt")
    expires = parse_time(environment["expiresAt"], "environment.expiresAt")
    current = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    if created > current or expires <= created or current >= expires:
        raise AcceptanceError("acceptance environment receipt is not currently valid")

    evidence = receipt["evidence"]
    required_evidence = set(EVIDENCE_BY_MODE[mode])
    if not isinstance(evidence, dict) or set(evidence) != required_evidence:
        raise AcceptanceError("required evidence set mismatch")
    for name in sorted(required_evidence):
        record = require_exact_keys(
            evidence[name],
            EVIDENCE_KEYS,
            f"evidence.{name}",
        )
        if record["status"] != "passed":
            raise AcceptanceError(f"evidence did not pass: {name}")
        require_sha256(
            record["artifactSha256"],
            f"evidence.{name}.artifactSha256",
        )
        require_id(record["issuer"], f"evidence.{name}.issuer")
        issued = parse_time(record["issuedAt"], f"evidence.{name}.issuedAt")
        evidence_expires = parse_time(
            record["expiresAt"],
            f"evidence.{name}.expiresAt",
        )
        if issued > current or evidence_expires <= issued or current >= evidence_expires:
            raise AcceptanceError(f"evidence is expired or future-dated: {name}")
        for field in (
            "sourceCommit",
            "sourceTree",
            "mergeCommit",
            "mergeTree",
        ):
            if record[field] != identities[field]:
                raise AcceptanceError(f"evidence identity drift: {name}.{field}")

    matrix = load_matrix()
    failpoints = receipt["failpoints"]
    if not isinstance(failpoints, dict) or set(failpoints) != set(matrix):
        raise AcceptanceError("failpoint coverage mismatch")
    for point_id, allowed_states in matrix.items():
        result = require_exact_keys(
            failpoints[point_id],
            FAILPOINT_RESULT_KEYS,
            f"failpoints.{point_id}",
        )
        if result["status"] != "passed":
            raise AcceptanceError(f"failpoint did not pass: {point_id}")
        require_sha256(
            result["artifactSha256"],
            f"failpoints.{point_id}.artifactSha256",
        )
        if result["observedState"] not in allowed_states:
            raise AcceptanceError(f"failpoint state is not permitted: {point_id}")

    approvals = require_exact_keys(
        receipt["approvals"],
        APPROVAL_NAMES,
        "approvals",
    )
    validate_approval(
        "security",
        approvals["security"],
        identities,
        required=True,
    )
    activation_required = mode in {"activation", "release"}
    release_required = mode == "release"
    validate_approval(
        "operator",
        approvals["operator"],
        identities,
        required=activation_required,
    )
    validate_approval(
        "release",
        approvals["release"],
        identities,
        required=release_required,
    )

    if receipt["independentAcceptance"] is not True:
        raise AcceptanceError("independent acceptance must be externally asserted")
    if receipt["activationApproved"] is not activation_required:
        raise AcceptanceError("activation approval flag does not match mode")
    if receipt["releaseApproved"] is not release_required:
        raise AcceptanceError("release approval flag does not match mode")

    return {
        "schema": "hepta.context-compiler.external-acceptance-validation.v1",
        "status": "passed",
        "mode": mode,
        "sourceCommit": identities["sourceCommit"],
        "sourceTree": identities["sourceTree"],
        "baseCommit": identities["baseCommit"],
        "mergeCommit": identities["mergeCommit"],
        "mergeTree": identities["mergeTree"],
        "receiptSha256": receipt["receiptSha256"],
        "evidenceCount": len(evidence),
        "failpointCount": len(failpoints),
        "sourceStateMutationAuthorized": False,
        "activationApproved": activation_required,
        "releaseApproved": release_required,
    }


def load_receipt(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size > MAX_RECEIPT_BYTES:
        raise AcceptanceError("acceptance receipt is missing or oversized")
    value = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=unique_object,
    )
    if not isinstance(value, dict):
        raise AcceptanceError("acceptance receipt root must be an object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument(
        "--mode",
        required=True,
        choices=sorted(EVIDENCE_BY_MODE),
    )
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--expected-source-tree", required=True)
    parser.add_argument("--expected-base", required=True)
    parser.add_argument("--expected-merge", required=True)
    parser.add_argument("--expected-merge-tree", required=True)
    parser.add_argument("--now", help="ISO-8601 validation time; defaults to current UTC")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        now = parse_time(args.now, "--now") if args.now else None
        report = validate_receipt(
            load_receipt(args.receipt),
            mode=args.mode,
            expected_source=args.expected_source,
            expected_source_tree=args.expected_source_tree,
            expected_base=args.expected_base,
            expected_merge=args.expected_merge,
            expected_merge_tree=args.expected_merge_tree,
            now=now,
        )
        encoded = json.dumps(report, sort_keys=True, indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(encoded, encoding="utf-8")
        sys.stdout.write(encoded)
        return 0
    except (
        AcceptanceError,
        OSError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
    ) as error:
        print(f"external acceptance rejected: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
