#!/usr/bin/env python3
"""Reconstruct the exact source-admission execution archive without overwriting."""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / "parts.json").read_bytes())
    if manifest["schema"] != "codex.hia.multipart-evidence.v1":
        raise SystemExit("unknown evidence schema")
    digest = hashlib.sha256()
    offset = 0
    with args.output.open("xb") as out:
        for part in manifest["parts"]:
            name = Path(part["path"])
            if name.name != part["path"] or part["offset"] != offset:
                raise SystemExit("noncanonical part path or offset")
            data = (root / name).read_bytes()
            git_blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            if (len(data) != part["bytes"] or hashlib.sha256(data).hexdigest() != part["sha256"]
                    or git_blob != part["git_blob"]):
                raise SystemExit("part bytes differ: " + part["path"])
            out.write(data)
            digest.update(data)
            offset += len(data)
    if offset != manifest["archive_bytes"] or digest.hexdigest() != manifest["archive_sha256"]:
        raise SystemExit("complete archive identity differs")
    print(json.dumps({"output": str(args.output), "bytes": offset, "sha256": digest.hexdigest()}))


if __name__ == "__main__":
    main()
