#!/usr/bin/env python3
"""Independent offline verifier of the Hepta Cell Split V1 four-owner transcript.

This is NOT an original-effect-owner readback, a deployment selector, a
production final-use issuer, or target-host attestation. A positive result
never authorizes activation, cutover, or physical split.

Source protocol: codex-rs/hepta-operator-acceptance/src/
cell_split_execution_owner.rs (reviewed against PR #1468 2026-10-13).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

STEP_NAMES = ("artifact_cas", "child_state_migration", "cns_route_cutover", "supervisor_generation_fence")
PLAN_FIELDS = frozenset({
    "splitId", "scopeDigest", "parentGeneration", "childGeneration",
    "parentArtifactDigest", "childArtifactDigest", "nduSnapshotDigest",
    "routeFenceDigest", "ownerIds",
})
TRUST_FIELDS = frozenset({"schema", "planDigest", "ownerIds", "verifyingKeys"})
INTENT_FIELDS = frozenset({
    "schema", "planDigest", "step", "ownerId", "idempotencyKey", "previousReceiptDigest",
})
RECEIPT_FIELDS = frozenset({
    "intent", "ownerSequence", "outputDigest", "ownerReceiptBytes",
    "ownerSignatureBytes", "receiptDigest",
})
TRANSCRIPT_FIELDS = frozenset({"plan", "receipts", "transcriptDigest"})
INTENT_SCHEMA = "hepta.learning.cell-split.execution-owner.v1"
TRUST_SCHEMA = "hepta.learning.cell-split.owner-trust-pins.v1"
SIGN_PREFIX = b"hepta.learning.cell-split.committed-effect.v1\0"
TRANSCRIPT_PREFIX = b"hepta.learning.cell-split.verified-transcript.v1\0"
HEX_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_RECEIPT_BYTES = 64 * 1024 // 2
P = 2**255 - 19
D = (-121665 * pow(121666, P - 2, P)) % P
SQRT_MINUS_ONE = pow(2, (P - 1) // 4, P)
ED25519_L = 2**252 + 27742317777372353535851937790883648493


class VerificationError(ValueError):
    """Untrusted evidence failed a fail-closed check."""


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise VerificationError(reason)


def canonical(value: Any) -> bytes:
    # Rust's durable::canonical_json uses serde_json::to_value, sort_value,
    # and serde_json::to_vec. Protocol fields contain no floats or maps with
    # non-string keys; non-ASCII characters are emitted without ASCII escape.
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def is_digest(value: Any) -> bool:
    return isinstance(value, str) and HEX_SHA256.fullmatch(value) is not None and value != "0" * 64


def exact_fields(value: Any, fields: frozenset[str], label: str) -> dict:
    require(type(value) is dict and value.keys() == fields, f"{label} fields mismatch")
    return value


def seq_bytes(value: Any, label: str, max_len: int) -> bytes:
    require(type(value) is list and len(value) <= max_len, f"{label} not bounded byte vector")
    require(all(type(item) is int and 0 <= item <= 255 for item in value), f"{label} has non-byte")
    return bytes(value)


def positive_int(value: Any, label: str) -> int:
    require(type(value) is int and 1 <= value <= 2**64 - 1, f"{label} not positive u64")
    return value


def no_duplicate_keys(pairs):
    obj = {}
    for key, value in pairs:
        require(key not in obj, f"duplicate JSON key: {key}")
        obj[key] = value
    return obj


def reject_json_constant(value: str):
    raise VerificationError(f"nonfinite JSON constant: {value}")


def load_json(path: Path) -> tuple[Any, bytes]:
    """Read a bounded, stable, one-link regular file without following links."""
    before = os.lstat(path)
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
            "evidence must be a one-link regular file")
    require(before.st_size <= MAX_FILE_BYTES, "evidence exceeds size limit")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        on_open = os.fstat(fd)
        require(stat.S_ISREG(on_open.st_mode), "evidence fd is not regular")
        require((on_open.st_dev, on_open.st_ino) == (before.st_dev, before.st_ino),
                "evidence replaced before open")
        with os.fdopen(fd, "rb", closefd=False) as fp:
            content = fp.read(MAX_FILE_BYTES + 1)
        after = os.fstat(fd)
        current = os.lstat(path)
        snapshot = lambda x: (x.st_dev, x.st_ino, x.st_size, x.st_mtime_ns, x.st_ctime_ns)
        require(snapshot(before) == snapshot(after) == snapshot(current),
                "evidence changed during read")
        require(len(content) == before.st_size and len(content) <= MAX_FILE_BYTES,
                "evidence truncated or exceeded size limit")
    finally:
        os.close(fd)
    try:
        result = json.loads(content, object_pairs_hook=no_duplicate_keys,
                            parse_constant=reject_json_constant)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise VerificationError(f"invalid JSON evidence: {exc}") from exc
    return result, content


def point_add(a: tuple[int, int], b: tuple[int, int]) -> tuple[int, int]:
    x1, y1 = a
    x2, y2 = b
    t = (D * x1 * x2 * y1 * y2) % P
    require(t not in (1, P - 1), "weak public key point")
    return (((x1 * y2 + y1 * x2) * pow((1 + t) % P, P - 2, P)) % P,
            ((y1 * y2 + x1 * x2) * pow((1 - t) % P, P - 2, P)) % P)


def key_is_weak(key: bytes) -> bool:
    """Match Ed25519 low-order public key rejection ([8]P == identity)."""
    require(len(key) == 32, "owner key must be 32 bytes")
    value = int.from_bytes(key, "little")
    y = value & ((1 << 255) - 1)
    sign = value >> 255
    require(y < P, "noncanonical owner key")
    denominator = (D * y * y + 1) % P
    require(denominator != 0, "invalid curve point")
    xx = ((y * y - 1) * pow(denominator, P - 2, P)) % P
    x = pow(xx, (P + 3) // 8, P)
    if x * x % P != xx:
        x = x * SQRT_MINUS_ONE % P
    require(x * x % P == xx, "owner key not on Ed25519")
    if x % 2 != sign:
        x = (-x) % P
    require(not (x == 0 and sign), "noncanonical owner key parity")
    point = (x, y)
    for _ in range(3):
        point = point_add(point, point)
    return point == (0, 1)


def validate_plan(value: Any) -> dict:
    p = exact_fields(value, PLAN_FIELDS, "plan")
    require(type(p["splitId"]) is str and 0 < len(p["splitId"].encode("utf-8")) <= 256,
            "invalid split ID")
    for field in ("scopeDigest", "parentArtifactDigest", "childArtifactDigest",
                  "nduSnapshotDigest", "routeFenceDigest"):
        require(is_digest(p[field]), f"invalid plan {field}")
    parent = positive_int(p["parentGeneration"], "parentGeneration")
    child = positive_int(p["childGeneration"], "childGeneration")
    require(parent < 2**64 - 1 and child == parent + 1, "parent/child generation drift")
    ids = p["ownerIds"]
    require(type(ids) is list and len(ids) == 4, "must pin four owners")
    require(all(type(n) is str and 0 < len(n.encode("utf-8")) <= 256 for n in ids), "bad owner ID")
    require(len(set(ids)) == 4, "owner IDs must be independent")
    return p


def validate_trust(value: Any, plan: dict, plan_digest: str) -> list[bytes]:
    trust = exact_fields(value, TRUST_FIELDS, "trust")
    require(trust["schema"] == TRUST_SCHEMA, "untrusted pin schema")
    require(trust["planDigest"] == plan_digest and trust["ownerIds"] == plan["ownerIds"],
            "independent owner trust pins drift")
    require(type(trust["verifyingKeys"]) is list and len(trust["verifyingKeys"]) == 4,
            "four externally pinned keys required")
    keys = [seq_bytes(raw, "owner verifying key", 32) for raw in trust["verifyingKeys"]]
    require(all(len(key) == 32 and not key_is_weak(key) for key in keys),
            "weak or malformed owner verifying key")
    require(len(set(keys)) == 4, "owner signer keys are not independent")
    return keys


def verify_transcript(transcript: Any, trust: Any) -> dict:
    t = exact_fields(transcript, TRANSCRIPT_FIELDS, "transcript")
    plan = validate_plan(t["plan"])
    plan_digest = sha256(canonical(plan))
    keys = validate_trust(trust, plan, plan_digest)
    receipts = t["receipts"]
    require(type(receipts) is list and len(receipts) == 4, "four exact receipt steps required")
    predecessor = plan_digest
    for index, item in enumerate(receipts):
        receipt = exact_fields(item, RECEIPT_FIELDS, f"receipt[{index}]")
        expected_key = sha256(
            (INTENT_SCHEMA + "\0" + plan_digest + "\0" + str(index) + "\0" + predecessor).encode()
        )
        intent = exact_fields(receipt["intent"], INTENT_FIELDS, f"intent[{index}]")
        require(intent == {
            "schema": INTENT_SCHEMA,
            "planDigest": plan_digest,
            "step": STEP_NAMES[index],
            "ownerId": plan["ownerIds"][index],
            "idempotencyKey": expected_key,
            "previousReceiptDigest": predecessor,
        }, f"receipt[{index}] step/owner/idempotency/predecessor mismatch")
        positive_int(receipt["ownerSequence"], "ownerSequence")
        content = seq_bytes(receipt["ownerReceiptBytes"], "ownerReceiptBytes", MAX_RECEIPT_BYTES)
        sig = seq_bytes(receipt["ownerSignatureBytes"], "ownerSignatureBytes", 64)
        require(bool(content) and len(sig) == 64, "empty source effect or malformed signature")
        # Align with ed25519-dalek verify_strict: canonical scalar and an R
        # point with no small-order component. This is independent of whether
        # the installed OpenSSL verifier currently rejects those encodings.
        require(int.from_bytes(sig[32:], "little") < ED25519_L,
                "noncanonical Ed25519 signature scalar")
        require(not key_is_weak(sig[:32]), "weak Ed25519 signature R point")
        require(is_digest(receipt["outputDigest"]) and receipt["outputDigest"] == sha256(content),
                "original owner receipt content digest mismatch")
        require(is_digest(receipt["receiptDigest"]), "invalid receipt digest")
        hash_input = dict(receipt, receiptDigest="")
        require(receipt["receiptDigest"] == sha256(canonical(hash_input)), "outer receipt digest mismatch")
        signed = dict(hash_input, ownerSignatureBytes=[])
        try:
            Ed25519PublicKey.from_public_bytes(keys[index]).verify(sig, SIGN_PREFIX + canonical(signed))
        except (ValueError, InvalidSignature) as exc:
            raise VerificationError(f"receipt[{index}] independent Ed25519 signature mismatch") from exc
        predecessor = receipt["receiptDigest"]
    expected_transcript = sha256(TRANSCRIPT_PREFIX + canonical(plan) + canonical(receipts))
    require(is_digest(t["transcriptDigest"]) and t["transcriptDigest"] == expected_transcript,
            "transcript digest mismatch")
    return {
        "schema": "hepta.learning.cell-split.independent-offline-observer.v1",
        "splitId": plan["splitId"],
        "transcriptDigest": expected_transcript,
        "completedSteps": 4,
        "originalOwnerSignatureChainValid": True,
        "originalOwnerLiveReadbackVerified": False,
        "targetHostAttestationVerified": False,
        "nduSelectionAndFinalUseVerified": False,
        "productionActivationAuthorized": False,
        "physicalSplitAuthorized": False,
    }


def parse_cli_outcome(value: Any) -> dict:
    require(type(value) is dict, "transcript must be JSON object")
    if value.get("schema") == "hepta.learning.cell-split.execution-cli-result.v1":
        require(value.get("productionActivationAuthorized") is False,
                "unexpected production activation claim in CLI outcome")
        require(value.get("complete") is True and value.get("completedSteps") == 4,
                "CLI has no complete four-step readback")
        require(type(value.get("transcript")) is dict, "CLI contains no full transcript")
        return value["transcript"]
    return value


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--transcript", type=Path, required=True,
                    help="native hepta-operator-acceptance transcript JSON")
    ap.add_argument("--trust-pins", type=Path, required=True,
                    help="the independently retained owner trust-pins JSON")
    ap.add_argument("--trust-pins-sha256", required=True,
                    help="SHA-256 of exact trust-pins bytes from an independent channel")
    args = ap.parse_args(argv)
    try:
        require(is_digest(args.trust_pins_sha256), "external trust pin must be lowercase SHA-256")
        trust, trusted_bytes = load_json(args.trust_pins)
        require(sha256(trusted_bytes) == args.trust_pins_sha256,
                "pinned trust file bytes do not match the out-of-band pin")
        transcript, _ = load_json(args.transcript)
        verified = verify_transcript(parse_cli_outcome(transcript), trust)
    except (VerificationError, OSError, ValueError, TypeError, OverflowError) as exc:
        print(json.dumps({
            "schema": "hepta.learning.cell-split.independent-offline-observer.v1",
            "originalOwnerSignatureChainValid": False,
            "productionActivationAuthorized": False,
            "physicalSplitAuthorized": False,
            "error": str(exc),
        }, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(verified, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
