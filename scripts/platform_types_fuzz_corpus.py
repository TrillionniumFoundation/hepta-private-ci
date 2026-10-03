#!/usr/bin/env python3
"""Seed bounded fuzz runs with frozen inputs that reach admitted product paths."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VECTOR_ROOT = Path("codex-rs/hepta-types")
EXPECTED_WIRE_KINDS = frozenset(
    {
        "prompt_delivery_observation_v2",
        "runtime_topology_candidate_v1",
        "random_stream_manifest_v1",
        "external_system_manifest_v1",
        "sensor_calibration_manifest_v1",
    }
)
SAFE_ID = re.compile(r"[a-zA-Z0-9_-]{1,96}\Z")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate vector key: {key}")
        value[key] = item
    return value


def seed_corpus(output: Path, *, root: Path = ROOT) -> dict[str, object]:
    records: list[dict[str, object]] = []
    wire_kinds: set[str] = set()
    seen: set[tuple[str, str]] = set()
    for filename, target, field in (
        ("CANONICAL_V1_CONFORMANCE.json", "types", "vectors"),
        ("PLATFORM_TYPES_WIRE_CONFORMANCE_V1.json", "wire", "validVectors"),
        ("MANIFEST_V1_CONFORMANCE.json", "wire", "validVectors"),
    ):
        source_path = VECTOR_ROOT / filename
        raw = (root / source_path).read_bytes()
        document = json.loads(raw, object_pairs_hook=_unique_object)
        vectors = document[field]
        if not isinstance(vectors, list) or not 1 <= len(vectors) <= 64:
            raise ValueError(f"missing or excessive frozen vectors: {source_path}")
        for vector in vectors:
            identity = vector["id"]
            if not isinstance(identity, str) or SAFE_ID.fullmatch(identity) is None:
                raise ValueError(f"unsafe seed identity: {identity!r}")
            if (target, identity) in seen:
                raise ValueError(f"duplicate seed identity: {identity}")
            seen.add((target, identity))
            if target == "types":
                payload = bytes.fromhex(vector["encodingHex"])
                if len(payload) != vector["encodedLength"]:
                    raise ValueError(f"canonical seed length mismatch: {identity}")
                if hashlib.sha256(payload).hexdigest() != vector["sha256"]:
                    raise ValueError(f"canonical seed digest mismatch: {identity}")
                kind = "HPTC"
                limit = 262144
            else:
                kind = vector["json"]["kind"]
                if kind not in EXPECTED_WIRE_KINDS:
                    raise ValueError(f"unknown wire protocol: {kind}")
                wire_kinds.add(kind)
                payload = json.dumps(
                    vector["json"],
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
                limit = 65536
            if not 0 < len(payload) <= limit:
                raise ValueError(f"seed exceeds {target} input bound: {identity}")
            path = Path(target) / "corpus" / identity
            records.append(
                {
                    "target": target,
                    "protocol": kind,
                    "seed": path.as_posix(),
                    "seedSha256": hashlib.sha256(payload).hexdigest(),
                    "seedBytes": len(payload),
                    "source": source_path.as_posix(),
                    "sourceSha256": hashlib.sha256(raw).hexdigest(),
                    "vectorId": identity,
                    "payload": payload,
                }
            )
    if wire_kinds != EXPECTED_WIRE_KINDS:
        raise ValueError(
            f"missing wire protocols: {sorted(EXPECTED_WIRE_KINDS - wire_kinds)}"
        )
    for record in records:
        path = output / str(record["seed"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(record.pop("payload"))
    receipt: dict[str, object] = {
        "schema": "hepta.platform-types.fuzz-corpus.v1",
        "schemaVersion": 1,
        "seeds": records,
        "claimBoundary": "frozen positive seeds only; not fuzz execution or qualification",
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "corpus-seeds.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    receipt = seed_corpus(args.output)
    print(f"platform.types fuzz corpus: {len(receipt['seeds'])} frozen positive seeds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
