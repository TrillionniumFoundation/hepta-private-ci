#!/usr/bin/env python3
"""Create and verify signed learning.artifacts drill and release receipts.

A passing external receipt requires an SSH Ed25519 detached signature from an
identity present in an independently provisioned allowed-signers file. This tool
never changes activation or release state; consumers must bind verified receipts
to the exact candidate SHA/tree and enforce their own authority policy.
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

SCHEMA = "hepta.learning-artifacts-drill-receipt.v1"
NAMESPACE = "hepta.learning-artifacts.drill.v1"
KINDS = {
    "backup_restore",
    "key_rotation",
    "target_filesystem",
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


class ReceiptError(RuntimeError):
    pass


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load_json(path: pathlib.Path) -> Any:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ReceiptError(f"cannot read {path}: {exc}") from exc
    if not raw or len(raw) > 4 * 1024 * 1024:
        raise ReceiptError(f"invalid JSON size for {path}")
    try:
        return json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReceiptError(f"invalid JSON in {path}: {exc}") from exc


def require_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ReceiptError(f"{name} must be a non-empty string")
    return value


def require_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ReceiptError(f"{name} must be a non-negative integer")
    return value


def validate_evidence(value: Any) -> None:
    if not isinstance(value, list) or not value:
        raise ReceiptError("evidence must be a non-empty list")
    names: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ReceiptError(f"evidence[{index}] must be an object")
        name = require_string(item.get("name"), f"evidence[{index}].name")
        if name in names:
            raise ReceiptError(f"duplicate evidence name: {name}")
        names.add(name)
        digest = require_string(item.get("sha256"), f"evidence[{index}].sha256")
        if not DIGEST_RE.fullmatch(digest):
            raise ReceiptError(f"invalid evidence digest for {name}")
        require_string(item.get("mediaType"), f"evidence[{index}].mediaType")
        require_string(item.get("locator"), f"evidence[{index}].locator")


def validate_claims(claims: Any) -> dict[str, Any]:
    if not isinstance(claims, dict):
        raise ReceiptError("claims must be an object")
    kind = require_string(claims.get("kind"), "kind")
    if kind not in KINDS:
        raise ReceiptError(f"unsupported receipt kind: {kind}")
    if claims.get("module") != "learning.artifacts":
        raise ReceiptError("module must be learning.artifacts")
    source_sha = require_string(claims.get("sourceSha"), "sourceSha")
    source_tree = require_string(claims.get("sourceTree"), "sourceTree")
    if not SHA_RE.fullmatch(source_sha) or not SHA_RE.fullmatch(source_tree):
        raise ReceiptError("sourceSha and sourceTree must be full lowercase Git object IDs")
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
        if assertions.get("restoredDigestMatches") is not True or assertions.get("oldGenerationRejected") is not True:
            raise ReceiptError("passing backup_restore requires digest match and rollback rejection")
    elif kind == "key_rotation":
        required = {"newKeyAccepted", "oldKeyRejectedAfterRevocation", "overlapWindowBounded"}
        if any(assertions.get(field) is not True for field in required):
            raise ReceiptError("passing key_rotation assertions are incomplete")
    elif kind == "target_filesystem":
        faults = assertions.get("faultsPassed")
        if not isinstance(faults, list) or not REQUIRED_TARGET_FAULTS.issubset(set(faults)):
            raise ReceiptError("target_filesystem is missing a required physical fault")
        if assertions.get("unknownNeverBecameNotStarted") is not True:
            raise ReceiptError("target_filesystem must prove unknown is never not-started")
    elif kind == "operator_acceptance":
        if assertions.get("runbookExecuted") is not True or assertions.get("independentOperator") is not True:
            raise ReceiptError("operator_acceptance must be independent and runbook-bound")
    elif kind == "canary":
        if assertions.get("noCorrectnessAlerts") is not True or assertions.get("rollbackReady") is not True:
            raise ReceiptError("canary must be alert-clean and rollback-ready")
    elif kind == "promotion":
        if assertions.get("canaryReceiptVerified") is not True or assertions.get("authorityApproved") is not True:
            raise ReceiptError("promotion requires verified canary and authority approval")
    elif kind == "rollback":
        if assertions.get("previousGenerationRestored") is not True or assertions.get("withdrawalFloorPreserved") is not True:
            raise ReceiptError("rollback must preserve the withdrawal floor")
    elif kind == "release":
        required = {
            "exactHeadQualified",
            "syntheticMergeQualified",
            "targetFilesystemQualified",
            "operatorAcceptanceVerified",
            "promotionReceiptVerified",
        }
        if any(assertions.get(field) is not True for field in required):
            raise ReceiptError("release assertions are incomplete")


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
    expected_receipt_digest = require_string(receipt.get("receiptDigest"), "receiptDigest")
    if not DIGEST_RE.fullmatch(expected_receipt_digest):
        raise ReceiptError("invalid receiptDigest")
    unsigned_receipt = dict(receipt)
    del unsigned_receipt["receiptDigest"]
    if sha256(canonical(unsigned_receipt)) != expected_receipt_digest:
        raise ReceiptError("receiptDigest mismatch")
    claims = validate_claims(receipt.get("claims"))
    payload = canonical(claims)
    if receipt.get("claimsDigest") != sha256(payload):
        raise ReceiptError("claimsDigest mismatch")
    signature = receipt.get("signature")
    if not isinstance(signature, dict):
        raise ReceiptError("signature must be an object")
    if signature.get("algorithm") != "ssh-ed25519" or signature.get("namespace") != NAMESPACE:
        raise ReceiptError("unsupported signature context")
    identity = require_string(signature.get("signerIdentity"), "signerIdentity")
    key_digest = require_string(signature.get("signerKeyDigest"), "signerKeyDigest")
    if not DIGEST_RE.fullmatch(key_digest):
        raise ReceiptError("invalid signerKeyDigest")
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
