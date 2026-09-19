#!/usr/bin/env python3
"""Independent Python verifier for Platform Types canonical digest V1."""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VECTOR = ROOT / "docs/lane-a-foundation/platform.types/CANONICAL_DIGEST_V1.json"
PREFIX = b"HEPTA-CANONICAL-DIGEST-V1\0"


def u16_bytes(value: bytes) -> bytes:
    if len(value) > 0xFFFF:
        raise ValueError("u16 length overflow")
    return struct.pack(">H", len(value)) + value


def u32_bytes(value: bytes) -> bytes:
    if len(value) > 0xFFFFFFFF:
        raise ValueError("u32 length overflow")
    return struct.pack(">I", len(value)) + value


def encode_value(value: dict[str, Any]) -> bytes:
    kind = value["type"]
    if kind == "bytes":
        return b"\x01" + u32_bytes(bytes.fromhex(value["hex"]))
    if kind == "text":
        return b"\x02" + u32_bytes(value["value"].encode("utf-8"))
    if kind == "u64":
        return b"\x03" + struct.pack(">Q", int(value["value"]))
    if kind == "i64":
        return b"\x04" + struct.pack(">q", int(value["value"]))
    if kind == "bool":
        return b"\x05" + bytes([1 if value["value"] else 0])
    if kind == "digest":
        digest = bytes.fromhex(value["hex"])
        if len(digest) != 32:
            raise ValueError("digest must be 32 bytes")
        return b"\x06" + digest
    if kind == "array":
        items = value["items"]
        return b"\x07" + struct.pack(">I", len(items)) + b"".join(
            encode_value(item) for item in items
        )
    if kind == "map":
        entries = sorted(value["entries"], key=lambda item: item["key"].encode("utf-8"))
        keys = [item["key"] for item in entries]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate map key")
        return b"\x08" + struct.pack(">I", len(entries)) + b"".join(
            u16_bytes(item["key"].encode("utf-8")) + encode_value(item["value"])
            for item in entries
        )
    raise ValueError(f"unknown canonical value type: {kind}")


def encode_vector(vector: dict[str, Any]) -> bytes:
    fields = sorted(vector["fields"], key=lambda item: item["name"].encode("utf-8"))
    names = [item["name"] for item in fields]
    if len(names) != len(set(names)):
        raise ValueError("duplicate field name")
    schema = vector["encodingSchemaVersion"]
    if schema <= 0:
        raise ValueError("schema version must be nonzero")
    return (
        PREFIX
        + u16_bytes(vector["typeId"].encode("utf-8"))
        + struct.pack(">I", schema)
        + struct.pack(">H", len(fields))
        + b"".join(
            u16_bytes(item["name"].encode("utf-8")) + encode_value(item["value"])
            for item in fields
        )
    )


def main() -> int:
    vector = json.loads(VECTOR.read_text(encoding="utf-8"))
    encoded = encode_vector(vector)
    expected = bytes.fromhex(vector["encodedHex"])
    if encoded != expected:
        raise SystemExit("platform.types vector bytes differ from frozen encodedHex")
    if len(encoded) != vector["encodedLength"]:
        raise SystemExit("platform.types vector encodedLength mismatch")
    digest = hashlib.sha256(encoded).hexdigest()
    if digest != vector["sha256"]:
        raise SystemExit("platform.types vector SHA-256 mismatch")
    print(f"platform.types canonical V1 python vector: ok ({len(encoded)} bytes, {digest})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
