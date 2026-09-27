#!/usr/bin/env python3
"""Independent Python verifier for cognitive.types V2 domain-bound vectors."""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VECTORS = ROOT / "qualification/cognitive-types-v1/golden-vectors-v2.json"
DOMAIN = b"hepta.cognitive.contract-domain.v1\0"
LEGACY_DOMAIN = b"hepta.cognitive.contract.canonical-json.v1\0"
INTENT_DOMAIN = b"hepta.cognitive.memory-write-intent.binding.v1\0"
REJECTION_CODES = {
    "authorization_rejected": 0,
    "snapshot_conflict": 1,
    "writer_fence_mismatch": 2,
    "candidate_rejected": 3,
    "capacity_exceeded": 4,
    "duplicate_intent_conflict": 5,
    "indeterminate": 6,
}


def canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha256(*parts: bytes) -> bytes:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part)
    return digest.digest()


def text(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return struct.pack(">Q", len(encoded)) + encoded


def domain_digest(vector: dict[str, object], payload: bytes) -> bytes:
    return sha256(
        DOMAIN,
        str(vector["schemaId"]).encode("utf-8"),
        b"\0",
        struct.pack(">I", int(vector["schemaVersion"])),
        b"\0",
        str(vector["contractId"]).encode("utf-8"),
        b"\0",
        str(vector["canonicalizationId"]).encode("utf-8"),
        b"\0",
        str(vector["unicodePolicyId"]).encode("utf-8"),
        b"\0",
        str(vector["digestAlgorithmId"]).encode("utf-8"),
        b"\0",
        payload,
    )


def verify_receipt(vector: dict[str, object]) -> None:
    payload = vector["payload"]
    assert isinstance(payload, dict)
    canonical_payload = canonical(payload)
    if canonical_payload.decode("utf-8") != vector["canonicalPayloadUtf8"]:
        raise SystemExit("canonical receipt payload mismatch")

    envelope = {
        "schema": vector["schemaId"],
        "schemaVersion": vector["schemaVersion"],
        "contract": vector["contractId"],
        "payload": payload,
    }
    if canonical(envelope).decode("utf-8") != vector["canonicalWireUtf8"]:
        raise SystemExit("canonical receipt envelope mismatch")

    outcome = payload["outcome"]
    assert isinstance(outcome, dict)
    if outcome.get("state") != "rejected":
        raise SystemExit("golden receipt must exercise tagged rejection")

    intent_digest = sha256(
        INTENT_DOMAIN,
        text(str(payload["intentId"])),
        bytes.fromhex(str(payload["candidateDigest"])),
        bytes.fromhex(str(payload["expectedSnapshotDigest"])),
        bytes.fromhex(str(payload["writerFenceDigest"])),
        bytes.fromhex(str(payload["authorizationDigest"])),
    )
    if intent_digest.hex() != payload["intentDigest"]:
        raise SystemExit("intent binding digest mismatch")

    rejection_code = REJECTION_CODES[str(outcome["rejectionCode"])]
    observed = outcome.get("observedSnapshotDigest")
    binding = b"".join(
        [
            str(vector["schemaId"]).encode("utf-8"),
            b"\0",
            struct.pack(">I", int(vector["schemaVersion"])),
            b"\0",
            text(str(payload["intentId"])),
            intent_digest,
            bytes.fromhex(str(payload["candidateDigest"])),
            bytes.fromhex(str(payload["authorizationDigest"])),
            bytes.fromhex(str(payload["writerFenceDigest"])),
            bytes.fromhex(str(payload["expectedSnapshotDigest"])),
            struct.pack(">Q", int(payload["expectedMemoryFrontier"])),
            text(str(payload["writerId"])),
            struct.pack(">Q", int(payload["issuedAtUnixMs"])),
            b"\x01",
            bytes([rejection_code]),
            b"\x01" if observed is not None else b"\x00",
            b"" if observed is None else bytes.fromhex(str(observed)),
            b"\x01" if bool(outcome["retryable"]) else b"\x00",
        ]
    )
    receipt_digest = domain_digest(vector, binding).hex()
    if receipt_digest != payload["receiptDigest"]:
        raise SystemExit("self-bound receipt digest mismatch")
    if receipt_digest != vector["receiptDigestSha256"]:
        raise SystemExit("receipt digest vector mismatch")

    legacy = sha256(
        LEGACY_DOMAIN,
        str(vector["contractId"]).encode("utf-8"),
        b"\0",
        canonical_payload,
    ).hex()
    if legacy != vector["legacyCanonicalDigestSha256"]:
        raise SystemExit("legacy canonical digest mismatch")

    if domain_digest(vector, canonical_payload).hex() != vector["domainBoundDigestSha256"]:
        raise SystemExit("domain-bound canonical digest mismatch")


def verify_unicode(vectors: list[dict[str, str]]) -> None:
    digests: set[str] = set()
    byte_sequences: set[str] = set()
    for vector in vectors:
        encoded = vector["text"].encode("utf-8")
        if encoded.hex() != vector["utf8Hex"]:
            raise SystemExit(f"Unicode byte mismatch for {vector['name']}")
        observed = hashlib.sha256(encoded).hexdigest()
        if observed != vector["sha256"]:
            raise SystemExit(f"Unicode digest mismatch for {vector['name']}")
        digests.add(observed)
        byte_sequences.add(encoded.hex())
    if len(digests) != len(vectors) or len(byte_sequences) != len(vectors):
        raise SystemExit("Unicode vectors were silently normalized")


def main() -> int:
    vectors = json.loads(VECTORS.read_text(encoding="utf-8"))
    verify_receipt(vectors["memoryWriteReceiptRejectedV1"])
    verify_unicode(vectors["unicodePreservationV1"])
    print(
        json.dumps(
            {
                "status": "PASS_COGNITIVE_TYPES_V2_DOMAIN_VECTORS",
                "vectorFile": str(VECTORS.relative_to(ROOT)),
                "receiptDigest": vectors["memoryWriteReceiptRejectedV1"][
                    "receiptDigestSha256"
                ],
                "domainBoundDigest": vectors["memoryWriteReceiptRejectedV1"][
                    "domainBoundDigestSha256"
                ],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
