#!/usr/bin/env python3
"""Restore unchanged audit bytes while preserving the repository blob limit."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / "cargo-deny-output-manifest.json").read_text())
    parts_dir = root / manifest["parts_directory"]
    parts = []
    for row in manifest["parts"]:
        name = Path(row["path"])
        if name.name != str(name):
            raise ValueError("unsafe evidence part path")
        data = (parts_dir / name).read_bytes()
        if len(data) != row["bytes"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise ValueError(f"evidence part differs: {name}")
        parts.append(data)
    compressed = b"".join(parts)
    if len(compressed) != manifest["compressed_bytes"] or hashlib.sha256(compressed).hexdigest() != manifest["compressed_sha256"]:
        raise ValueError("original compressed audit differs")
    raw = gzip.decompress(compressed)
    if len(raw) != manifest["original_bytes"] or hashlib.sha256(raw).hexdigest() != manifest["original_sha256"]:
        raise ValueError("original audit JSON differs")
    json.loads(raw)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(compressed)
    print(json.dumps({"bytes": len(compressed), "sha256": manifest["compressed_sha256"],
                      "original_bytes": len(raw), "original_sha256": manifest["original_sha256"]}, indent=2))


if __name__ == "__main__":
    main()
