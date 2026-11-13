#!/usr/bin/env python3
"""Losslessly encode a retained artifact into policy-bounded Git text blobs."""
import argparse
import base64
import gzip
import hashlib
import json
from pathlib import Path


def identity(data):
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
    }


def pack(source, destination):
    raw = source.read_bytes()
    compressed = gzip.compress(raw, compresslevel=9, mtime=0)
    destination.mkdir(parents=True, exist_ok=True)
    parts = []
    recovered = []
    for offset in range(0, len(compressed), 240_000):
        chunk = compressed[offset:offset + 240_000]
        name = f"{source.name}.gz.part-{len(parts) + 1:03d}.b64"
        encoded = base64.b64encode(chunk) + b"\n"
        if len(encoded) > 512_000:
            raise ValueError("new evidence blob exceeds the original policy")
        path = destination / name
        if path.exists() and path.read_bytes() != encoded:
            raise ValueError("refusing to replace a different retained part")
        path.write_bytes(encoded)
        decoded = base64.b64decode(path.read_bytes()[:-1], validate=True)
        if decoded != chunk or base64.b64encode(decoded) + b"\n" != encoded:
            raise ValueError("noncanonical or changed part")
        recovered.append(decoded)
        parts.append({"name": name, "encoded": identity(encoded), "decoded": identity(chunk)})
    if b"".join(recovered) != compressed or gzip.decompress(b"".join(recovered)) != raw:
        raise ValueError("lossless reconstruction failed")
    manifest = {
        "format": "hepta-bounded-lossless-evidence-v1",
        "raw_name": source.name,
        "raw": identity(raw),
        "gzip": identity(compressed),
        "encoding": "gzip mtime=0; split compressed bytes in order into at most 240000-byte chunks; canonical standard base64 plus one LF per text blob",
        "maximum_new_blob_bytes": 512_000,
        "parts": parts,
        "local_lossless_reconstruction_verified": True,
        "full_git_part_readback_verified_here": False,
        "qualification": False,
    }
    encoded_manifest = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    manifest_path = destination / "ENCODING_MANIFEST.json"
    if manifest_path.exists() and manifest_path.read_bytes() != encoded_manifest:
        raise ValueError("refusing to replace a different encoding manifest")
    manifest_path.write_bytes(encoded_manifest)
    print(json.dumps({"manifest": identity(encoded_manifest), "raw": identity(raw), "parts": len(parts)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    pack(args.source, args.destination)
