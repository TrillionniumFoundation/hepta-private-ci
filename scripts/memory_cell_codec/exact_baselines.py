"""Actual lossless full-record baselines; metadata is never silently omitted."""

import json
import lzma
from pathlib import Path
import sqlite3
import zlib

from quantized_adapter import canonical_bytes
from tensor_contract import sha256


def measure_baselines(records, destination):
    """Persist and round-trip exact complete records and marked semantic projection."""
    if (
        type(records) is not list
        or not 1 <= len(records) <= 20_000
        or any(type(r) is not dict for r in records)
    ):
        raise ValueError("bounded complete records required")
    complete = canonical_bytes(records)
    if len(complete) > 8 * 1024 * 1024:
        raise ValueError("source ledger byte budget")
    projection_fields = ("scope", "entity", "relation", "value")
    projection_available = all(set(projection_fields) <= set(r) for r in records)
    variants_to_measure = [("complete_records", complete)]
    if projection_available:
        projection = [{k: r[k] for k in projection_fields} for r in records]
        variants_to_measure.append(("semantic_only", canonical_bytes(projection)))
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    result = dict(
        schema="hepta.memory-exact-storage-baselines.v1",
        records=len(records),
        source_records_sha256=sha256(complete),
        source_metadata_retained=True,
        semantic_projection_available=projection_available,
        semantic_projection_unavailable_reason=None
        if projection_available
        else "original records do not share the legacy scope/entity/relation/value schema",
        semantic_projection_omits_source_metadata=projection_available,
        measurements={},
    )
    for label, payload in variants_to_measure:
        variants = {
            "json": payload,
            "zlib9": zlib.compress(payload, 9),
            "lzma6": lzma.compress(payload, preset=6),
        }
        assert zlib.decompress(variants["zlib9"]) == payload
        assert lzma.decompress(variants["lzma6"]) == payload
        for suffix, data in variants.items():
            name = f"{label}.{suffix}"
            (destination / name).write_bytes(data)
            result["measurements"][name] = dict(
                bytes=len(data), sha256=sha256(data), lossless=True
            )
    database = destination / "complete_records.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA page_size=4096")
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute(
            "CREATE TABLE memory (ordinal INTEGER PRIMARY KEY, payload BLOB NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO memory VALUES (?, ?)",
            [(i, canonical_bytes(r)) for i, r in enumerate(records)],
        )
        connection.commit()
        loaded = [
            json.loads(row[0])
            for row in connection.execute("SELECT payload FROM memory ORDER BY ordinal")
        ]
        if canonical_bytes(loaded) != complete:
            raise ValueError("SQLite exact-source round trip failed")
    payload = database.read_bytes()
    result["measurements"][database.name] = dict(
        bytes=len(payload), sha256=sha256(payload), lossless=True
    )
    result.update(compression_advantage_proven=False, production_accepted=False)
    (destination / "baseline-receipt.json").write_bytes(canonical_bytes(result))
    return result
