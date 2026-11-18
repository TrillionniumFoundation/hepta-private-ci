#!/usr/bin/env python3
"""Reconstruct the byte-exact archives described by ARCHIVES.json."""

import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / "ARCHIVES.json").read_bytes())
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    restored = []
    for archive in manifest["archives"]:
        name = Path(archive["name"])
        if name.is_absolute() or len(name.parts) != 1:
            raise ValueError("archive name is not a filename")
        hasher = hashlib.sha256()
        count = 0
        with (output / name).open("xb") as stream:
            for part in archive["parts"]:
                source = (root / part["path"]).resolve(strict=True)
                if not source.is_relative_to(root):
                    raise ValueError("archive part escapes the evidence directory")
                raw = source.read_bytes()
                if (
                    len(raw) != part["bytes"]
                    or hashlib.sha256(raw).hexdigest() != part["sha256"]
                ):
                    raise ValueError("archive part differs: " + part["path"])
                stream.write(raw)
                hasher.update(raw)
                count += len(raw)
        if count != archive["bytes"] or hasher.hexdigest() != archive["sha256"]:
            raise ValueError("restored archive identity differs: " + str(name))
        restored.append(
            {"name": str(name), "bytes": count, "sha256": hasher.hexdigest()}
        )
    print(json.dumps({"status": "ARCHIVES_RESTORED", "archives": restored}, indent=2))


if __name__ == "__main__":
    main()
