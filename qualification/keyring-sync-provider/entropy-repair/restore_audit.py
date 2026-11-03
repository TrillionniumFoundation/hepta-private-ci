#!/usr/bin/env python3
"""Restore the exact original keyring audit from bounded binary parts."""

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
    parts = []
    for row in manifest["gzip"]["parts"]:
        name = Path(row["path"])
        if name.name != str(name):
            raise ValueError("unsafe audit part path")
        data = (root / manifest["gzip"]["parts_directory"] / name).read_bytes()
        if len(data) != row["bytes"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise ValueError(f"audit part differs: {name}")
        parts.append(data)
    compressed = b"".join(parts)
    raw = gzip.decompress(compressed)
    for data, key in [(compressed, "gzip"), (raw, "uncompressed")]:
        if len(data) != manifest[key]["bytes"] or hashlib.sha256(data).hexdigest() != manifest[key]["sha256"]:
            raise ValueError(f"original {key} audit differs")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(compressed)
    print(json.dumps({"bytes": len(compressed), "sha256": manifest["gzip"]["sha256"],
                      "uncompressed_bytes": len(raw), "uncompressed_sha256": manifest["uncompressed"]["sha256"]}, indent=2))


if __name__ == "__main__":
    main()
