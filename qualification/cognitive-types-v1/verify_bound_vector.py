#!/usr/bin/env python3
"""Independent Python oracle for the schema/version-bound cognitive digest."""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

DOMAIN = b"hepta.cognitive.contract.bound-digest.v1\0"
FIXTURE = Path(__file__).with_name("bound_vector.json")


def canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def component(value: bytes) -> bytes:
    return struct.pack(">Q", len(value)) + value


def main() -> int:
    vector = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload = canonical(vector["payload"])
    material = b"".join(
        [
            DOMAIN,
            component(vector["schema"].encode("utf-8")),
            struct.pack(">I", vector["schemaVersion"]),
            component(vector["contract"].encode("utf-8")),
            component(vector["canonicalizationAlgorithm"].encode("utf-8")),
            component(payload),
        ]
    )
    observed = hashlib.sha256(material).hexdigest()
    if observed != vector["expectedBoundDigest"]:
        raise SystemExit(f"bound cognitive digest mismatch: {observed}")
    print(
        json.dumps(
            {
                "status": "PASS_COGNITIVE_TYPES_BOUND_VECTOR_PYTHON",
                "digest": observed,
                "canonicalPayloadBytes": len(payload),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
