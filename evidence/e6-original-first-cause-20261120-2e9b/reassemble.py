#!/usr/bin/env python3
"""Reassemble the unchanged E6 evidence archive after verifying every part."""
import argparse
import hashlib
import json
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="new archive path; existing files are refused")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / "archive-parts.json").read_text(encoding="utf-8"))
    chunks = []
    for index, part in enumerate(manifest["parts"]):
        expected = f"original-evidence.tar.xz.part-{index:02d}"
        if part["path"] != expected or part["bytes"] > 480000:
            raise ValueError("unexpected part identity or size")
        data = (root / expected).read_bytes()
        if len(data) != part["bytes"] or hashlib.sha256(data).hexdigest() != part["sha256"]:
            raise ValueError(f"part verification failed: {expected}")
        chunks.append(data)
    data = b"".join(chunks)
    if len(data) != manifest["archive_bytes"] or hashlib.sha256(data).hexdigest() != manifest["archive_sha256"]:
        raise ValueError("complete archive verification failed")
    with args.output.open("xb") as output:
        output.write(data)
    print(f"Verified {len(chunks)} parts; wrote {len(data)} bytes; SHA256 {manifest['archive_sha256']}")

if __name__ == "__main__":
    main()
