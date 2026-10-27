"""Actual compressed storage, bounded chunks and independently hashed payloads."""

from pathlib import Path
import zlib

from .contracts import canonical, file_identity, sha256


PART_BYTES = 480000


def store_payload(directory, prefix, raw):
    path = Path(directory)
    files = {}
    for index, start in enumerate(range(0, len(raw), PART_BYTES), 1):
        name = f"{prefix}.part{index:03d}"
        with (path / name).open("xb") as stream:
            stream.write(raw[start:start + PART_BYTES])
        files[name] = file_identity(path / name)
    if not files:
        raise ValueError("empty payload is not allowed")
    return {"bytes": len(raw), "sha256": sha256(raw), "files": files}


def load_payload(directory, prefix, record, *, limit=16000000):
    path = Path(directory)
    files = record["files"]
    if not files or len(files) > 40 or record["bytes"] > limit:
        raise ValueError("payload exceeds the bounded inventory")
    names = [f"{prefix}.part{i:03d}" for i in range(1, len(files) + 1)]
    if set(names) != set(files):
        raise ValueError("payload part names or sequence differ")
    chunks = []
    for name in names:
        item = path / name
        if item.is_symlink() or not item.is_file() or not 0 < item.stat().st_size <= PART_BYTES:
            raise ValueError("payload part is missing, linked or exceeds its limit")
        raw = item.read_bytes()
        if {"bytes": len(raw), "sha256": sha256(raw)} != files[name]:
            raise ValueError("payload part identity differs")
        chunks.append(raw)
    raw = b"".join(chunks)
    if len(raw) != record["bytes"] or sha256(raw) != record["sha256"]:
        raise ValueError("assembled payload identity differs")
    return raw


def compressed_json(directory, prefix, value):
    raw = canonical(value) + b"\n"
    record = store_payload(directory, prefix, zlib.compress(raw, level=9))
    return {**record, "encoding": "zlib-compressed-UTF8-JSON", "uncompressed_bytes": len(raw), "uncompressed_sha256": sha256(raw)}


def bounded_decompress(raw, maximum):
    decoder = zlib.decompressobj()
    decoded = decoder.decompress(raw, maximum + 1)
    if len(decoded) > maximum or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError("compressed payload exceeds bounds or has an invalid stream")
    return decoded
