#!/usr/bin/env python3
"""Restore unchanged machine-readable provenance without executing it."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / "compressed-json-evidence.json").read_text())
    for row in manifest["files"]:
        source, target = Path(row["gzip_path"]), Path(row["original_path"])
        if any(p.is_absolute() or ".." in p.parts for p in [source, target]):
            raise ValueError("unsafe evidence path")
        packed = (root / source).read_bytes()
        if len(packed) != row["gzip_bytes"] or hashlib.sha256(packed).hexdigest() != row["gzip_sha256"]:
            raise ValueError("compressed evidence differs")
        raw = gzip.decompress(packed)
        if len(raw) != row["original_bytes"] or hashlib.sha256(raw).hexdigest() != row["original_sha256"]:
            raise ValueError("original evidence differs")
        json.loads(raw)
        output = args.output_directory / target
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(raw)
    print(json.dumps({"restored_original_files": len(manifest["files"]), "source_commit": manifest["source_commit"]}))


if __name__ == "__main__":
    main()
