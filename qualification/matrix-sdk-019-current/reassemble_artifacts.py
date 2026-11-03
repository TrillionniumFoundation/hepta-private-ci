#!/usr/bin/env python3
"""Restore exact qualification bytes outside the checkout from bounded parts."""

import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / "artifact-parts.json").read_text())
    for artifact in manifest["artifacts"]:
        chunks = []
        for part in artifact["parts"]:
            data = (root / part["path"]).read_bytes()
            if len(data) != part["bytes"] or hashlib.sha256(data).hexdigest() != part["sha256"]:
                raise RuntimeError("qualification part differs: " + part["path"])
            chunks.append(data)
        data = b"".join(chunks)
        if len(data) != artifact["bytes"] or hashlib.sha256(data).hexdigest() != artifact["sha256"]:
            raise RuntimeError("qualification reconstruction differs: " + artifact["path"])
        destination = args.output / artifact["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as stream:
            stream.write(data)
        print(json.dumps({"path": artifact["path"], "bytes": len(data), "sha256": artifact["sha256"]}))


if __name__ == "__main__":
    main()
