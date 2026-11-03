"""Bounded, hashed compressed evidence documents; no large opaque model pickle."""

import json
from pathlib import Path

from .artifacts import bounded_decompress, compressed_json, load_payload
from .contracts import sha256, write_json


def write_document(path, value):
    path = Path(path)
    if path.exists():
        raise ValueError("evidence document cannot be overwritten")
    prefix = path.name + ".zlib"
    payload = compressed_json(path.parent, prefix, value)
    envelope = {
        "schema": "hepta.memory.v5.compressed-evidence.v1",
        "prefix": prefix,
        "payload": payload,
    }
    write_json(path, envelope)
    return envelope


def read_document(path):
    path = Path(path)
    envelope = json.loads(path.read_bytes())
    if (
        set(envelope) != {"schema", "prefix", "payload"}
        or envelope["schema"] != "hepta.memory.v5.compressed-evidence.v1"
        or envelope["prefix"] != path.name + ".zlib"
    ):
        raise ValueError("invalid compressed evidence envelope")
    descriptor = envelope["payload"]
    encoded = load_payload(path.parent, envelope["prefix"], descriptor)
    raw = bounded_decompress(encoded, 64000000)
    if (
        len(raw) != descriptor["uncompressed_bytes"]
        or sha256(raw) != descriptor["uncompressed_sha256"]
    ):
        raise ValueError("decompressed evidence identity differs")
    return json.loads(raw)
