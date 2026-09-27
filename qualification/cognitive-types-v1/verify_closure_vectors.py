#!/usr/bin/env python3
"""Independent exact-integer oracle for all registered cognitive V1 schemas."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "codex-rs/hepta-cognitive-types/tests/fixtures/closure_vectors.json"
PROFILE = "canonical-json-utf8-sorted-keys-integer-only-preserve-unicode-v1"


def canonical(value: object) -> bytes:
    def validate(item: object) -> None:
        if isinstance(item, float):
            raise ValueError("floating JSON numbers are outside this profile")
        if isinstance(item, str):
            item.encode("utf-8", errors="strict")
        elif isinstance(item, list):
            for child in item:
                validate(child)
        elif isinstance(item, dict):
            for key, child in item.items():
                validate(key)
                validate(child)
    validate(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def component(value: bytes) -> bytes:
    return len(value).to_bytes(8, "big") + value


def main() -> None:
    raw = CORPUS.read_bytes()
    corpus = json.loads(raw)
    if corpus["canonicalizationAlgorithm"] != PROFILE:
        raise ValueError("wrong canonicalization profile")
    names: set[str] = set()
    results = []
    for row in corpus["vectors"]:
        if row["name"] in names:
            raise ValueError("duplicate vector name")
        names.add(row["name"])
        payload = canonical(row["payload"])
        legacy = hashlib.sha256(b"hepta.cognitive.contract.canonical-json.v1\0" +
                               row["contract"].encode() + b"\0" + payload).hexdigest()
        bound = hashlib.sha256(b"hepta.cognitive.contract.bound-digest.v1\0" +
                              component(row["schema"].encode()) + (1).to_bytes(4, "big") +
                              component(row["contract"].encode()) + component(PROFILE.encode()) +
                              component(payload)).hexdigest()
        if (legacy, bound) != (row["legacyDigest"], row["boundDigest"]):
            raise ValueError(f"digest drift for {row['name']}")
        results.append({"name": row["name"], "bound_digest": bound})
    if len({row["contract"] for row in corpus["vectors"]}) != 12 or "u64-maximum" not in names:
        raise ValueError("incomplete corpus")
    print(json.dumps({"schema": "hepta.cognitive-types.corpus-result.v1", "status": "passed",
                      "runtime": "python", "vector_count": len(results),
                      "corpus_sha256": hashlib.sha256(raw).hexdigest(), "vectors": results}, sort_keys=True))


if __name__ == "__main__":
    main()
