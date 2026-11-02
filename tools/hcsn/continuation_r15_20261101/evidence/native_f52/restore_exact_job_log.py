"""Restore the exact recorded gzip bytes from hash-bound gzip envelopes."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path


def digest(data):
    return hashlib.sha256(data).hexdigest()


def restore(manifest_path, output):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["schema"] != "hcsn.gzip-envelope-transport.v1":
        raise ValueError("unsupported transport schema")
    original = manifest["original"]
    pieces = []
    offset = 0
    for index, chunk in enumerate(manifest["chunks"]):
        name = chunk["file"]
        if Path(name).name != name or name in ("", ".", ".."):
            raise ValueError("chunk must be a local filename")
        if chunk["index"] != index or chunk["offset"] != offset:
            raise ValueError("noncontiguous chunk sequence")
        packed = (manifest_path.parent / name).read_bytes()
        if len(packed) != chunk["bytes"] or digest(packed) != chunk["sha256"]:
            raise ValueError("gzip envelope identity mismatch")
        raw = gzip.decompress(packed)
        if len(raw) != chunk["raw_bytes"] or digest(raw) != chunk["raw_sha256"]:
            raise ValueError("raw gzip piece identity mismatch")
        offset += len(raw)
        if offset > original["gzip_bytes"]:
            raise ValueError("chunks exceed original gzip length")
        pieces.append(raw)
    restored = b"".join(pieces)
    if len(restored) != original["gzip_bytes"]:
        raise ValueError("incomplete original gzip")
    if digest(restored) != original["gzip_sha256"]:
        raise ValueError("original gzip identity mismatch")
    decoded = gzip.decompress(restored)
    if len(decoded) != original["decoded_utf8_bytes"]:
        raise ValueError("decoded log length mismatch")
    if digest(decoded) != original["decoded_utf8_sha256"]:
        raise ValueError("decoded log identity mismatch")
    with output.open("xb") as stream:
        stream.write(restored)
    return {"output": str(output), **original}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(restore(args.manifest, args.output), indent=2))


if __name__ == "__main__":
    main()
