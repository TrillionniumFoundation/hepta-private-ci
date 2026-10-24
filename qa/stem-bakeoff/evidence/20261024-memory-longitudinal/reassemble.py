"""Reassemble byte-pinned archive parts without executing their contents."""

import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parts", type=Path, default=Path(__file__).parent)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    metadata = json.loads((args.parts / "parts.json").read_text())
    whole = hashlib.sha256()
    total = 0
    with args.output.open("xb") as output:
        for item in metadata["parts"]:
            name = item["path"]
            if Path(name).name != name or item["offset"] != total:
                raise ValueError("noncontiguous part or nonlocal path")
            path = args.parts / name
            if path.is_symlink():
                raise ValueError("part must be a regular local file")
            raw = path.read_bytes()
            git_sha = hashlib.sha1(
                b"blob " + str(len(raw)).encode() + b"\0" + raw
            ).hexdigest()
            if (
                len(raw) != item["bytes"]
                or hashlib.sha256(raw).hexdigest() != item["sha256"]
                or git_sha != item["git_blob_sha1"]
            ):
                raise ValueError("archive part failed byte verification: " + name)
            output.write(raw)
            whole.update(raw)
            total += len(raw)
    if (
        total != metadata["archive_bytes"]
        or whole.hexdigest() != metadata["archive_sha256"]
    ):
        raise ValueError(
            "complete archive failed byte verification; partial output retained"
        )
    print(
        json.dumps(dict(bytes=total, sha256=whole.hexdigest(), output=str(args.output)))
    )


if __name__ == "__main__":
    main()
