"""Verify every published evidence part and optionally reassemble the archive."""

import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parts", type=Path, default=Path(__file__).parent / "artifacts/PARTS.json")
    parser.add_argument("--output", type=Path, help="Create a new reassembled gzip file; existing paths are refused")
    args = parser.parse_args()
    manifest = json.loads(args.parts.read_text())
    root = Path(__file__).resolve().parents[2]
    whole, total = hashlib.sha256(), 0
    destination = args.output.open("xb") if args.output else None
    try:
        for part in manifest["parts"]:
            relative = Path(part["path"])
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Invalid relative evidence path")
            path = root / relative
            if path.is_symlink() or not path.is_file() or path.stat().st_size != part["bytes"]:
                raise ValueError(f"Missing or wrong-size evidence part: {relative}")
            sha = hashlib.sha256()
            git = hashlib.sha1(b"blob " + str(part["bytes"]).encode() + b"\0")
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1 << 20), b""):
                    sha.update(block)
                    git.update(block)
                    whole.update(block)
                    total += len(block)
                    if destination:
                        destination.write(block)
            if sha.hexdigest() != part["sha256"] or git.hexdigest() != part["git_blob_sha"]:
                raise ValueError(f"Corrupt evidence part: {relative}")
        if total != manifest["whole"]["bytes"] or whole.hexdigest() != manifest["whole"]["sha256"]:
            raise ValueError("Reassembled evidence identity mismatch")
    finally:
        if destination:
            destination.close()
    print(json.dumps(dict(status="verified", parts=len(manifest["parts"]), bytes=total,
                          sha256=whole.hexdigest(), output=str(args.output) if args.output else None)))


if __name__ == "__main__":
    main()
