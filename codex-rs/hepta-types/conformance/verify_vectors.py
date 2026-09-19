#!/usr/bin/env python3
"""Independent Python oracle for platform.types canonical digest V1."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
VECTOR = ROOT / "codex-rs/hepta-types/CANONICAL_V1_CONFORMANCE.json"
DOMAIN = b"hepta.platform.types.canonical-digest.v1"


def u16(value: int) -> bytes:
    return value.to_bytes(2, "big")


def u32(value: int) -> bytes:
    return value.to_bytes(4, "big")


def label(value: str) -> bytes:
    encoded = value.encode()
    allowed = all(
        97 <= byte <= 122
        or 48 <= byte <= 57
        or byte in b"._-:"
        for byte in encoded
    )
    if (
        not encoded
        or len(encoded) > 128
        or not chr(encoded[0]).isalnum()
        or not chr(encoded[-1]).isalnum()
        or not allowed
    ):
        raise ValueError("invalid label")
    return u16(len(encoded)) + encoded


def encode_value(value: dict) -> bytes:
    kind = value["type"]
    if kind == "bool":
        return b"\x01" + bytes([1 if value["value"] else 0])
    if kind == "u64":
        return b"\x02" + int(value["value"]).to_bytes(8, "big")
    if kind == "u128":
        return b"\x03" + int(value["value"]).to_bytes(16, "big")
    if kind == "i64":
        return b"\x04" + int(value["value"]).to_bytes(8, "big", signed=True)
    if kind == "bytes":
        payload = bytes.fromhex(value["hex"])
        return b"\x05" + u32(len(payload)) + payload
    if kind == "text":
        payload = value["value"].encode()
        if b"\0" in payload:
            raise ValueError("NUL text")
        return b"\x06" + u32(len(payload)) + payload
    if kind == "digest":
        payload = bytes.fromhex(value["hex"])
        if len(payload) != 32:
            raise ValueError("digest length")
        return b"\x07" + payload
    if kind == "stable_id":
        payload = value["value"].encode()
        return b"\x08" + u16(len(payload)) + payload
    if kind == "array":
        items = value["items"]
        return b"\x09" + u32(len(items)) + b"".join(encode_value(item) for item in items)
    if kind == "map":
        entries = sorted(value["entries"], key=lambda item: item["key"].encode())
        keys = [item["key"] for item in entries]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate map key")
        return b"\x0a" + u32(len(entries)) + b"".join(
            label(item["key"]) + encode_value(item["value"]) for item in entries
        )
    raise ValueError(f"unknown value type: {kind}")


def encode(vector: dict) -> bytes:
    type_id = vector["typeId"].encode()
    fields = sorted(vector["fields"], key=lambda item: item["name"].encode())
    names = [item["name"] for item in fields]
    if len(names) != len(set(names)):
        raise ValueError("duplicate field")
    output = (
        b"HPTC"
        + u16(1)
        + u16(len(DOMAIN))
        + DOMAIN
        + u16(len(type_id))
        + type_id
        + u32(vector["schemaVersion"])
        + u32(len(fields))
    )
    output += b"".join(
        label(field["name"]) + encode_value(field["value"]) for field in fields
    )
    return output


def main() -> None:
    document = json.loads(VECTOR.read_text(encoding="utf-8"))
    if document["domain"].encode() != DOMAIN or document["encodingVersion"] != 1:
        raise SystemExit("conformance header mismatch")
    for vector in document["vectors"]:
        encoded = encode(vector)
        if len(encoded) != vector["encodedLength"]:
            raise SystemExit(f"{vector['id']}: encoded length mismatch")
        if encoded.hex() != vector["encodingHex"]:
            raise SystemExit(f"{vector['id']}: canonical bytes mismatch")
        if hashlib.sha256(encoded).hexdigest() != vector["sha256"]:
            raise SystemExit(f"{vector['id']}: digest mismatch")
    print(f"platform.types Python canonical vectors: {len(document['vectors'])} passed")


if __name__ == "__main__":
    main()
