#!/usr/bin/env python3
"""Independent Python oracle for cognitive.types canonical JSON V1 vectors."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

DOMAIN = b"hepta.cognitive.contract.canonical-json.v1\0"
CONTRACT = "ModalitySpanRefV1"
SCHEMA = "hepta.hnmf.modality-span-ref.v1"
EXPECTED_DIGEST = "1e1c8f2232a1f6ddfea98400f3c2ae9d29ecd39ae2a2ff0e0bac70f91f0ad273"

PAYLOAD = {
    "spanId": "span:1",
    "modality": "text",
    "assetSha256": "a" * 64,
    "range": {"kind": "byte_range", "start": 0, "end": 4},
    "preprocessorManifestSha256": "b" * 64,
    "featureBlobSha256": None,
    "symbolicProjectionSha256": None,
    "uncertaintyPpm": 10_000,
    "privacyClass": "agent_private",
    "redactionMaskSha256": None,
}


def canonical(value: object) -> bytes:
    # Python's sorted-key compact JSON is intentionally independent from the
    # Rust recursive writer but implements the same V1 contract.
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def main() -> int:
    payload_bytes = canonical(PAYLOAD)
    envelope = {
        "schema": SCHEMA,
        "schemaVersion": 1,
        "contract": CONTRACT,
        "payload": PAYLOAD,
    }
    envelope_bytes = canonical(envelope)
    digest = hashlib.sha256(
        DOMAIN + CONTRACT.encode("ascii") + b"\0" + payload_bytes
    ).hexdigest()

    expected_envelope = (
        '{"contract":"ModalitySpanRefV1","payload":{'
        '"assetSha256":"' + "a" * 64 + '",'
        '"featureBlobSha256":null,'
        '"modality":"text",'
        '"preprocessorManifestSha256":"' + "b" * 64 + '",'
        '"privacyClass":"agent_private",'
        '"range":{"end":4,"kind":"byte_range","start":0},'
        '"redactionMaskSha256":null,'
        '"spanId":"span:1",'
        '"symbolicProjectionSha256":null,'
        '"uncertaintyPpm":10000},'
        '"schema":"hepta.hnmf.modality-span-ref.v1",'
        '"schemaVersion":1}'
    ).encode("utf-8")

    if envelope_bytes != expected_envelope:
        raise SystemExit("canonical envelope mismatch")
    if digest != EXPECTED_DIGEST:
        raise SystemExit(f"canonical digest mismatch: {digest}")

    wire = (ROOT / "codex-rs/hepta-cognitive-types/src/wire.rs").read_text(
        encoding="utf-8"
    )
    tests = (ROOT / "codex-rs/hepta-cognitive-types/src/contract_tests.rs").read_text(
        encoding="utf-8"
    )
    for token in [DOMAIN[:-1].decode("ascii"), CONTRACT, SCHEMA]:
        if token not in wire:
            raise SystemExit(f"Rust wire implementation missing token: {token}")
    if EXPECTED_DIGEST not in tests:
        raise SystemExit("Rust golden-vector digest is not pinned to the Python oracle")

    print(
        json.dumps(
            {
                "status": "PASS_COGNITIVE_TYPES_V1_CROSS_LANGUAGE_VECTOR",
                "contract": CONTRACT,
                "schema": SCHEMA,
                "canonicalEnvelopeBytes": len(envelope_bytes),
                "digest": digest,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
