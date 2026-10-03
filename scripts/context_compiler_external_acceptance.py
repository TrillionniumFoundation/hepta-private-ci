#!/usr/bin/env python3
"""Fail-closed validator for externally signed context.compiler acceptance receipts."""

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = ROOT / "qualification/context-compiler/FAILPOINT_MATRIX.json"
MAX_RECEIPT_BYTES = 2 * 1024 * 1024
OID = re.compile(r"[0-9a-f]{40}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
SID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}\Z")
SENSITIVE = (
    "secret",
    "credential",
    "privatekey",
    "private_key",
    "access_token",
    "api_key",
)

BASE_EVIDENCE = (
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
    "independent": BASE_EVIDENCE,
    "activation": (*BASE_EVIDENCE, "canaryRollback"),
    "release": (*BASE_EVIDENCE, "canaryRollback"),
}
TOP = {
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
IDS = {"sourceCommit", "sourceTree", "baseCommit", "mergeCommit", "mergeTree"}
ENV = {
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
EVIDENCE = {
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
FP_RESULT = {"status", "observedState", "artifactSha256"}
APPROVAL = {"status", "approverId", "approvalSha256", "issuedAt", *IDS}
APPROVAL_NAMES = {"security", "operator", "release"}
MATRIX_TOP = {"schema", "module", "rules", "points"}
MATRIX_RULES = {
    "everyPointRequired",
    "status",
    "unresolvedIsNeverFinal",
    "blindReplayForbidden",
    "identityBinding",
}
MATRIX_BINDINGS = {
    "sourceCommit",
    "sourceTree",
    "mergeCommit",
    "mergeTree",
    "hostImageDigest",
    "providerTenant",
}


class AcceptanceError(ValueError):
    pass


def unique(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise AcceptanceError(f"duplicate JSON key: {key}")
        out[key] = value
    return out


def reject_constant(value):
    raise AcceptanceError(f"non-standard JSON constant: {value}")


def canonical_sha256(value):
    value = dict(value)
    value.pop("receiptSha256", None)
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def exact(value, keys, field):
    if not isinstance(value, dict) or set(value) != keys:
        actual = sorted(value) if isinstance(value, dict) else type(value).__name__
        raise AcceptanceError(f"{field} keys mismatch: {actual}")
    return value


def matched(value, pattern, field):
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise AcceptanceError(f"invalid {field}")
    return value


def oid(value, field):
    return matched(value, OID, field)


def sha(value, field):
    return matched(value, SHA, field)


def sid(value, field):
    return matched(value, SID, field)


def timestamp(value, field):
    if not isinstance(value, str) or len(value) > 64:
        raise AcceptanceError(f"invalid {field}")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError as error:
        raise AcceptanceError(f"invalid {field}") from error
    if parsed.tzinfo is None:
        raise AcceptanceError(f"timezone missing: {field}")
    return parsed.astimezone(dt.timezone.utc)


def reject_sensitive(value, path="receipt"):
    if isinstance(value, dict):
        for key, item in value.items():
            if any(part in key.lower() for part in SENSITIVE):
                raise AcceptanceError(f"sensitive key forbidden: {path}.{key}")
            reject_sensitive(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            reject_sensitive(item, f"{path}[{index}]")
    elif isinstance(value, str) and len(value) > 4096:
        raise AcceptanceError(f"unbounded string: {path}")


def decode(path):
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=unique,
        parse_constant=reject_constant,
    )


def load_matrix(path=MATRIX_PATH):
    value = decode(path)
    exact(value, MATRIX_TOP, "failpoint matrix")
    if (
        value["schema"] != "hepta.context-compiler.failpoint-matrix.v1"
        or value["module"] != "context.compiler"
    ):
        raise AcceptanceError("unsupported failpoint matrix")
    rules = exact(value["rules"], MATRIX_RULES, "failpoint rules")
    if (
        rules["everyPointRequired"] is not True
        or rules["status"] != "passed"
        or rules["unresolvedIsNeverFinal"] is not True
        or rules["blindReplayForbidden"] is not True
        or not isinstance(rules["identityBinding"], list)
        or set(rules["identityBinding"]) != MATRIX_BINDINGS
        or len(rules["identityBinding"]) != len(MATRIX_BINDINGS)
    ):
        raise AcceptanceError("failpoint matrix rules are not fail-closed")
    if not isinstance(value["points"], list) or not value["points"]:
        raise AcceptanceError("empty failpoint matrix")
    out = {}
    for point in value["points"]:
        exact(point, {"id", "phase", "allowedObservedStates"}, "failpoint")
        point_id = sid(point["id"], "failpoint id")
        sid(point["phase"], "failpoint phase")
        states = point["allowedObservedStates"]
        if (
            not isinstance(states, list)
            or not states
            or any(
                not isinstance(item, str) or not SID.fullmatch(item) for item in states
            )
            or len(states) != len(set(states))
            or point_id in out
        ):
            raise AcceptanceError(f"invalid failpoint: {point_id}")
        out[point_id] = set(states)
    return out


def validate_approval(name, value, identities, required, now):
    if value is None:
        if required:
            raise AcceptanceError(f"{name} approval required")
        return None
    if not required:
        raise AcceptanceError(f"{name} approval not permitted")
    value = exact(value, APPROVAL, f"approvals.{name}")
    if value["status"] != "approved":
        raise AcceptanceError(f"{name} approval not approved")
    approver = sid(value["approverId"], f"{name} approver")
    sha(value["approvalSha256"], f"{name} approval digest")
    if timestamp(value["issuedAt"], f"{name} issuedAt") > now:
        raise AcceptanceError(f"{name} approval is future-dated")
    for field in IDS:
        if value[field] != identities[field]:
            raise AcceptanceError(f"{name} approval identity drift: {field}")
    return approver


def validate_receipt(
    receipt,
    *,
    mode,
    expected_source,
    expected_source_tree,
    expected_base,
    expected_merge,
    expected_merge_tree,
    now=None,
):
    exact(receipt, TOP, "receipt")
    reject_sensitive(receipt)
    if (
        receipt["schema"] != "hepta.context-compiler.external-acceptance.v1"
        or receipt["mode"] != mode
        or mode not in EVIDENCE_BY_MODE
    ):
        raise AcceptanceError("receipt schema or mode mismatch")
    sha(receipt["receiptSha256"], "receipt digest")
    if receipt["receiptSha256"] != canonical_sha256(receipt):
        raise AcceptanceError("receipt canonical digest mismatch")

    identities = exact(receipt["identities"], IDS, "identities")
    expected = {
        "sourceCommit": expected_source,
        "sourceTree": expected_source_tree,
        "baseCommit": expected_base,
        "mergeCommit": expected_merge,
        "mergeTree": expected_merge_tree,
    }
    for field, wanted in expected.items():
        oid(wanted, f"expected {field}")
        oid(identities[field], f"identities.{field}")
        if identities[field] != wanted:
            raise AcceptanceError(f"immutable identity mismatch: {field}")

    current = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    environment = exact(receipt["environment"], ENV, "environment")
    for field in (
        "environmentId",
        "runnerIdentity",
        "kernelIdentity",
        "filesystemIdentity",
        "providerTenant",
    ):
        sid(environment[field], f"environment.{field}")
    sha(environment["runnerImageDigest"], "runner image digest")
    sha(environment["hostImageDigest"], "host image digest")
    created = timestamp(environment["createdAt"], "environment.createdAt")
    expires = timestamp(environment["expiresAt"], "environment.expiresAt")
    if created > current or expires <= created or current >= expires:
        raise AcceptanceError("environment receipt is not current")

    required = set(EVIDENCE_BY_MODE[mode])
    evidence = receipt["evidence"]
    if not isinstance(evidence, dict) or set(evidence) != required:
        raise AcceptanceError("required evidence set mismatch")
    for name in required:
        record = exact(evidence[name], EVIDENCE, f"evidence.{name}")
        if record["status"] != "passed":
            raise AcceptanceError(f"evidence failed: {name}")
        sha(record["artifactSha256"], f"{name} artifact")
        sid(record["issuer"], f"{name} issuer")
        issued = timestamp(record["issuedAt"], f"{name}.issuedAt")
        expiry = timestamp(record["expiresAt"], f"{name}.expiresAt")
        if issued > current or expiry <= issued or current >= expiry:
            raise AcceptanceError(f"evidence expired or future-dated: {name}")
        for field in ("sourceCommit", "sourceTree", "mergeCommit", "mergeTree"):
            if record[field] != identities[field]:
                raise AcceptanceError(f"evidence identity drift: {name}.{field}")

    matrix = load_matrix()
    failpoints = receipt["failpoints"]
    if not isinstance(failpoints, dict) or set(failpoints) != set(matrix):
        raise AcceptanceError("failpoint coverage mismatch")
    for point_id, allowed in matrix.items():
        result = exact(failpoints[point_id], FP_RESULT, f"failpoints.{point_id}")
        if result["status"] != "passed" or result["observedState"] not in allowed:
            raise AcceptanceError(f"failpoint failed: {point_id}")
        sha(result["artifactSha256"], f"{point_id} artifact")

    approvals = exact(receipt["approvals"], APPROVAL_NAMES, "approvals")
    activation = mode in {"activation", "release"}
    release = mode == "release"
    approvers = [
        validate_approval("security", approvals["security"], identities, True, current),
        validate_approval(
            "operator", approvals["operator"], identities, activation, current
        ),
        validate_approval(
            "release", approvals["release"], identities, release, current
        ),
    ]
    present = [item for item in approvers if item is not None]
    if len(present) != len(set(present)):
        raise AcceptanceError("approvals must be independent")
    if receipt["independentAcceptance"] is not True:
        raise AcceptanceError("independent acceptance missing")
    if (
        receipt["activationApproved"] is not activation
        or receipt["releaseApproved"] is not release
    ):
        raise AcceptanceError("approval flags do not match mode")

    return {
        "schema": "hepta.context-compiler.external-acceptance-validation.v1",
        "status": "passed",
        "mode": mode,
        **identities,
        "receiptSha256": receipt["receiptSha256"],
        "evidenceCount": len(evidence),
        "failpointCount": len(failpoints),
        "sourceStateMutationAuthorized": False,
        "activationApproved": activation,
        "releaseApproved": release,
    }


def load_receipt(path):
    if not path.is_file() or path.stat().st_size > MAX_RECEIPT_BYTES:
        raise AcceptanceError("receipt missing or oversized")
    value = decode(path)
    if not isinstance(value, dict):
        raise AcceptanceError("receipt root must be an object")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--mode", required=True, choices=sorted(EVIDENCE_BY_MODE))
    for name in ("source", "source-tree", "base", "merge", "merge-tree"):
        parser.add_argument(f"--expected-{name}", required=True)
    parser.add_argument("--now")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = validate_receipt(
            load_receipt(args.receipt),
            mode=args.mode,
            expected_source=args.expected_source,
            expected_source_tree=args.expected_source_tree,
            expected_base=args.expected_base,
            expected_merge=args.expected_merge,
            expected_merge_tree=args.expected_merge_tree,
            now=timestamp(args.now, "--now") if args.now else None,
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
