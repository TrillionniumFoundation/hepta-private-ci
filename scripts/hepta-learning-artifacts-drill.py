#!/usr/bin/env python3
"""Create and verify signed learning.artifacts drill and release receipts.

A passing external receipt requires an SSH Ed25519 detached signature from an
identity present in an independently provisioned allowed-signers file. Every
passing receipt is bound to an immutable repository candidate and qualification
readiness manifest. This tool never changes activation or release state;
consumers must enforce an independent authority policy.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import pathlib
import re
import subprocess
import tempfile
from typing import Any

SCHEMA = "hepta.learning-artifacts-drill-receipt.v2"
NAMESPACE = "hepta.learning-artifacts.drill.v2"
KINDS = {
    "backup_restore",
    "key_rotation",
    "target_filesystem",
    "product_execution",
    "operator_acceptance",
    "canary",
    "promotion",
    "rollback",
    "release",
}
EXTERNAL_PASS_KINDS = frozenset(KINDS)
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_TARGET_FAULTS = {
    "sigkill",
    "fsync_failure",
    "rename_failure",
    "disk_full",
    "physical_power_loss",
}
REQUIRED_PRODUCT_STEPS = {
    "publish",
    "current_head_update",
    "exact_pinned_load",
    "bounded_read",
    "revoke",
    "restart_recovery",
    "rollback",
    "credential_rotation",
    "cold_start_restore",
}


class ReceiptError(RuntimeError):
    pass


def canonical(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode("utf-8")


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _strict_pairs(rows: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in rows:
        if key in value:
            raise ReceiptError(f"duplicate JSON field: {key}")
        value[key] = item
    return value


def _reject_constant(value: str) -> None:
    raise ReceiptError(f"non-finite JSON value: {value}")


def load_json(path: pathlib.Path) -> Any:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ReceiptError(f"cannot read {path}: {exc}") from exc
    if not raw or len(raw) > 4 * 1024 * 1024:
        raise ReceiptError(f"invalid JSON size for {path}")
    try:
        return json.loads(
            raw,
            object_pairs_hook=_strict_pairs,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReceiptError(f"invalid JSON in {path}: {exc}") from exc


def require_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ReceiptError(f"{name} must be a non-empty string")
    return value


def require_int(value: Any, name: str, *, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ReceiptError(f"{name} must be a non-negative integer")
    if positive and value == 0:
        raise ReceiptError(f"{name} must be positive")
    return value


def require_digest(value: Any, name: str) -> str:
    digest = require_string(value, name)
    if not DIGEST_RE.fullmatch(digest):
        raise ReceiptError(f"{name} must be a lowercase SHA-256 digest")
    return digest


def require_true(assertions: dict[str, Any], fields: set[str], message: str) -> None:
    if any(assertions.get(field) is not True for field in fields):
        raise ReceiptError(message)


def validate_evidence(value: Any) -> None:
    if not isinstance(value, list) or not value:
        raise ReceiptError("evidence must be a non-empty list")
    names: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ReceiptError(f"evidence[{index}] must be an object")
        if set(item) != {"name", "sha256", "mediaType", "locator"}:
            raise ReceiptError(f"evidence[{index}] contains an unknown or missing field")
        name = require_string(item.get("name"), f"evidence[{index}].name")
        if name in names:
            raise ReceiptError(f"duplicate evidence name: {name}")
        names.add(name)
        require_digest(item.get("sha256"), f"evidence[{index}].sha256")
        require_string(item.get("mediaType"), f"evidence[{index}].mediaType")
        require_string(item.get("locator"), f"evidence[{index}].locator")


def validate_claims(claims: Any) -> dict[str, Any]:
    if not isinstance(claims, dict):
        raise ReceiptError("claims must be an object")
    required = {
        "module",
        "kind",
        "sourceSha",
        "sourceTree",
        "readinessManifestSha256",
        "qualificationRunId",
        "qualificationRunAttempt",
        "targetFingerprint",
        "startedAt",
        "completedAt",
        "outcome",
        "assertions",
        "evidence",
    }
    if set(claims) != required:
        raise ReceiptError("claims contain an unknown or missing field")
    kind = require_string(claims.get("kind"), "kind")
    if kind not in KINDS:
        raise ReceiptError(f"unsupported receipt kind: {kind}")
    if claims.get("module") != "learning.artifacts":
        raise ReceiptError("module must be learning.artifacts")
    source_sha = require_string(claims.get("sourceSha"), "sourceSha")
    source_tree = require_string(claims.get("sourceTree"), "sourceTree")
    if not SHA_RE.fullmatch(source_sha) or not SHA_RE.fullmatch(source_tree):
        raise ReceiptError("sourceSha and sourceTree must be full lowercase Git object IDs")
    require_digest(claims.get("readinessManifestSha256"), "readinessManifestSha256")
    require_string(claims.get("qualificationRunId"), "qualificationRunId")
    require_int(
        claims.get("qualificationRunAttempt"),
        "qualificationRunAttempt",
        positive=True,
    )
    require_string(claims.get("targetFingerprint"), "targetFingerprint")
    started = require_int(claims.get("startedAt"), "startedAt")
    completed = require_int(claims.get("completedAt"), "completedAt")
    if completed < started:
        raise ReceiptError("completedAt precedes startedAt")
    outcome = require_string(claims.get("outcome"), "outcome")
    if outcome not in {"pass", "fail", "pending"}:
        raise ReceiptError("outcome must be pass, fail or pending")
    validate_evidence(claims.get("evidence"))
    assertions = claims.get("assertions")
    if not isinstance(assertions, dict):
        raise ReceiptError("assertions must be an object")
    if outcome == "pass":
        validate_passing_assertions(kind, assertions)
    return claims


def validate_passing_assertions(kind: str, assertions: dict[str, Any]) -> None:
    if kind == "backup_restore":
        require_true(
            assertions,
            {"restoredDigestMatches", "oldGenerationRejected", "independentAnchorMatched"},
            "passing backup_restore assertions are incomplete",
        )
    elif kind == "key_rotation":
        require_true(
            assertions,
            {"newKeyAccepted", "oldKeyRejectedAfterRevocation", "overlapWindowBounded", "interruptedRotationRecovered"},
            "passing key_rotation assertions are incomplete",
        )
    elif kind == "target_filesystem":
        faults = assertions.get("faultsPassed")
        if not isinstance(faults, list) or any(not isinstance(item, str) for item in faults):
            raise ReceiptError("target_filesystem faultsPassed must be a string list")
        if not REQUIRED_TARGET_FAULTS.issubset(set(faults)):
            raise ReceiptError("target_filesystem is missing a required physical fault")
        require_true(
            assertions,
            {
                "unknownNeverBecameNotStarted",
                "fileSyncVerified",
                "directorySyncVerified",
                "atomicReplaceVerified",
                "encryptedAtRest",
                "singleHostWriter",
            },
            "target_filesystem capability assertions are incomplete",
        )
        require_string(assertions.get("filesystemType"), "filesystemType")
        require_digest(assertions.get("mountOptionsHash"), "mountOptionsHash")
        require_string(assertions.get("keySource"), "keySource")
        require_string(assertions.get("keyIdentifier"), "keyIdentifier")
        require_int(assertions.get("keyRotationEpoch"), "keyRotationEpoch", positive=True)
        require_digest(assertions.get("capabilityAttestation"), "capabilityAttestation")
    elif kind == "product_execution":
        steps = assertions.get("lifecycleStepsPassed")
        if not isinstance(steps, list) or any(not isinstance(item, str) for item in steps):
            raise ReceiptError("product_execution lifecycleStepsPassed must be a string list")
        if not REQUIRED_PRODUCT_STEPS.issubset(set(steps)):
            raise ReceiptError("product_execution is missing a required lifecycle step")
        require_true(
            assertions,
            {
                "productionComposition",
                "fixtureFallbackAbsent",
                "syntheticCredentialAbsent",
                "testBypassAbsent",
                "coldStartFromIndependentAnchor",
            },
            "product_execution composition assertions are incomplete",
        )
    elif kind == "operator_acceptance":
        require_true(
            assertions,
            {
                "runbookExecuted",
                "independentOperator",
                "candidateReadinessVerified",
                "rollbackExecuted",
            },
            "operator_acceptance must be independent, readiness-bound and rollback-tested",
        )
    elif kind == "canary":
        require_true(
            assertions,
            {"noCorrectnessAlerts", "rollbackReady", "sameCandidateAndTarget"},
            "canary must be alert-clean, identity-bound and rollback-ready",
        )
    elif kind == "promotion":
        require_true(
            assertions,
            {"canaryReceiptVerified", "authorityApproved", "sameCandidateAndTarget"},
            "promotion requires verified canary, exact identity and authority approval",
        )
    elif kind == "rollback":
        require_true(
            assertions,
            {"previousGenerationRestored", "withdrawalFloorPreserved", "independentAnchorMatched"},
            "rollback must preserve withdrawal and independent-anchor invariants",
        )
    elif kind == "release":
        require_true(
            assertions,
            {
                "readinessManifestVerified",
                "exactHeadQualified",
                "syntheticMergeQualified",
                "targetFilesystemQualified",
                "productExecutionVerified",
                "operatorAcceptanceVerified",
                "promotionReceiptVerified",
            },
            "release assertions are incomplete",
        )


def public_key_digest(signing_key: pathlib.Path) -> str:
    try:
        public = subprocess.check_output(
            ["ssh-keygen", "-y", "-f", str(signing_key)],
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReceiptError(f"cannot derive signing public key: {exc}") from exc
    return sha256(public.strip() + b"\n")


def sign(payload: bytes, signing_key: pathlib.Path) -> bytes:
    with tempfile.TemporaryDirectory(prefix="hepta-artifact-sign-") as directory:
        data = pathlib.Path(directory) / "claims.json"
        data.write_bytes(payload)
        try:
            subprocess.run(
                ["ssh-keygen", "-Y", "sign", "-f", str(signing_key), "-n", NAMESPACE, str(data)],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            raise ReceiptError(f"cannot sign receipt claims: {exc}") from exc
        return data.with_suffix(data.suffix + ".sig").read_bytes()


def verify_signature(payload: bytes, signature: bytes, identity: str, allowed_signers: pathlib.Path) -> None:
    with tempfile.TemporaryDirectory(prefix="hepta-artifact-verify-") as directory:
        signature_path = pathlib.Path(directory) / "claims.sig"
        signature_path.write_bytes(signature)
        try:
            subprocess.run(
                [
                    "ssh-keygen",
                    "-Y",
                    "verify",
                    "-f",
                    str(allowed_signers),
                    "-I",
                    identity,
                    "-n",
                    NAMESPACE,
                    "-s",
                    str(signature_path),
                ],
                input=payload,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            raise ReceiptError(f"receipt signature verification failed: {exc}") from exc


def build(claims_path: pathlib.Path, signing_key: pathlib.Path, identity: str, output: pathlib.Path) -> None:
    claims = validate_claims(load_json(claims_path))
    payload = canonical(claims)
    signature = sign(payload, signing_key)
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "claims": claims,
        "claimsDigest": sha256(payload),
        "signature": {
            "algorithm": "ssh-ed25519",
            "namespace": NAMESPACE,
            "signerIdentity": identity,
            "signerKeyDigest": public_key_digest(signing_key),
            "value": base64.b64encode(signature).decode("ascii"),
        },
    }
    receipt["receiptDigest"] = sha256(canonical(receipt))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(json.dumps(receipt, sort_keys=True, indent=2).encode("utf-8") + b"\n")


def verify(path: pathlib.Path, allowed_signers: pathlib.Path) -> dict[str, Any]:
    receipt = load_json(path)
    if not isinstance(receipt, dict) or receipt.get("schema") != SCHEMA:
        raise ReceiptError("wrong receipt schema")
    if set(receipt) != {"schema", "claims", "claimsDigest", "signature", "receiptDigest"}:
        raise ReceiptError("receipt contains an unknown or missing field")
    expected_receipt_digest = require_digest(receipt.get("receiptDigest"), "receiptDigest")
    unsigned_receipt = dict(receipt)
    del unsigned_receipt["receiptDigest"]
    if sha256(canonical(unsigned_receipt)) != expected_receipt_digest:
        raise ReceiptError("receiptDigest mismatch")
    claims = validate_claims(receipt.get("claims"))
    payload = canonical(claims)
    if receipt.get("claimsDigest") != sha256(payload):
        raise ReceiptError("claimsDigest mismatch")
    signature = receipt.get("signature")
    if not isinstance(signature, dict) or set(signature) != {
        "algorithm", "namespace", "signerIdentity", "signerKeyDigest", "value"
    }:
        raise ReceiptError("signature contains an unknown or missing field")
    if signature.get("algorithm") != "ssh-ed25519" or signature.get("namespace") != NAMESPACE:
        raise ReceiptError("unsupported signature context")
    identity = require_string(signature.get("signerIdentity"), "signerIdentity")
    require_digest(signature.get("signerKeyDigest"), "signerKeyDigest")
    encoded = require_string(signature.get("value"), "signature.value")
    try:
        raw_signature = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise ReceiptError("invalid signature base64") from exc
    verify_signature(payload, raw_signature, identity, allowed_signers)
    if claims["outcome"] == "pass" and claims["kind"] in EXTERNAL_PASS_KINDS:
        return receipt
    if claims["outcome"] != "pass":
        return receipt
    raise ReceiptError("unsupported passing receipt kind")


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("--claims", required=True, type=pathlib.Path)
    build_parser.add_argument("--signing-key", required=True, type=pathlib.Path)
    build_parser.add_argument("--signer-identity", required=True)
    build_parser.add_argument("--output", required=True, type=pathlib.Path)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("receipt", type=pathlib.Path)
    verify_parser.add_argument("--allowed-signers", required=True, type=pathlib.Path)
    args = parser.parse_args()
    try:
        if args.command == "build":
            build(args.claims, args.signing_key, args.signer_identity, args.output)
        else:
            verify(args.receipt, args.allowed_signers)
    except ReceiptError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
