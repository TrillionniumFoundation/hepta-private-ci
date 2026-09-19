#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

PREFIX = b"HEPTA-CANONICAL-DIGEST-V1\\x00"
MAX_COLLECTION = 256 * 1024
TOKEN = re.compile(r"^[a-z0-9._-]+$")
TYPE_TAGS = {
    "bytes": 1,
    "text": 2,
    "u64": 3,
    "i64": 4,
    "bool": 5,
    "digest32": 6,
    "stable_id": 7,
}


def value_bytes(field: dict[str, object]) -> bytes:
    kind = str(field["type"])
    value = field["value"]
    if kind == "bytes":
        return bytes.fromhex(str(value))
    if kind in {"text", "stable_id"}:
        return str(value).encode("utf-8")
    if kind == "u64":
        return int(str(value)).to_bytes(8, "big", signed=False)
    if kind == "i64":
        return int(str(value)).to_bytes(8, "big", signed=True)
    if kind == "bool":
        if not isinstance(value, bool):
            raise AssertionError("bool vector value must be JSON boolean")
        return b"\\x01" if value else b"\\x00"
    if kind == "digest32":
        decoded = bytes.fromhex(str(value))
        if len(decoded) != 32:
            raise AssertionError("digest32 vector must decode to 32 bytes")
        return decoded
    raise AssertionError(f"unknown canonical value type: {kind}")


def encode(vector: dict[str, object]) -> bytes:
    domain = str(vector["domain"])
    domain_bytes = domain.encode("ascii")
    if not domain or len(domain_bytes) > 128 or not TOKEN.fullmatch(domain):
        raise AssertionError(f"invalid domain: {domain}")

    fields = list(vector["fields"])
    if len(fields) > 1024:
        raise AssertionError("too many fields")
    names = [str(field["name"]) for field in fields]
    if names != sorted(names) or len(set(names)) != len(names):
        raise AssertionError("field names must be strictly sorted and unique")

    output = bytearray(PREFIX)
    output.extend(len(domain_bytes).to_bytes(2, "big"))
    output.extend(domain_bytes)
    output.extend(len(fields).to_bytes(2, "big"))

    for field in fields:
        name = str(field["name"])
        name_bytes = name.encode("ascii")
        if not name or len(name_bytes) > 128 or not TOKEN.fullmatch(name):
            raise AssertionError(f"invalid field name: {name}")
        kind = str(field["type"])
        payload = value_bytes(field)
        output.extend(len(name_bytes).to_bytes(2, "big"))
        output.extend(name_bytes)
        output.append(TYPE_TAGS[kind])
        output.extend(len(payload).to_bytes(4, "big"))
        output.extend(payload)

    if len(output) > MAX_COLLECTION:
        raise AssertionError("canonical collection exceeds 256 KiB")
    return bytes(output)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    vector_path = root / "codex-rs/hepta-types/testdata/canonical_digest_v1_vectors.json"
    document = json.loads(vector_path.read_text(encoding="utf-8"))
    assert document["schema"] == "hepta.platform-types.canonical-digest-v1.vectors"
    assert document["schemaVersion"] == 1
    vectors = document["vectors"]
    assert vectors, "vector corpus must not be empty"
    for vector in vectors:
        encoded = encode(vector)
        assert encoded.hex() == vector["canonicalHex"], vector["name"]
        assert hashlib.sha256(encoded).hexdigest() == vector["sha256"], vector["name"]
    print(f"verified {len(vectors)} platform.types canonical vectors in Python")


if __name__ == "__main__":
    main()
