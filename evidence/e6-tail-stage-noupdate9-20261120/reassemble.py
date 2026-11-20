#!/usr/bin/env python3
"""Reassemble the retained NoUpdate9 originals and verify each archived member."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile

EXPECTED_ARCHIVE = "63ac249e451dc9f390933e1e0a5a05a31a59e504f1f9a982c7e640276a131a88"
EXPECTED_MANIFEST = "1b532e43247829bf6ac473cbca3d1836a35671f48ffcf0ea540b7bbe7594e7fb"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    index = json.loads((here / "archive-parts.json").read_text())
    data = bytearray()
    for row in index["parts"]:
        part = here / row["name"]
        if part.name != row["name"] or part.is_symlink():
            raise ValueError("invalid part name or symlink")
        raw = part.read_bytes()
        if len(raw) != row["bytes"] or hashlib.sha256(raw).hexdigest() != row["sha256"]:
            raise ValueError("part bytes differ: " + row["name"])
        data.extend(raw)
    if len(data) != index["archive_bytes"] or hashlib.sha256(data).hexdigest() != EXPECTED_ARCHIVE:
        raise ValueError("complete archive bytes differ")
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:xz") as archive:
        members = archive.getmembers()
        if not all(member.isfile() and not Path(member.name).is_absolute()
                   and ".." not in Path(member.name).parts for member in members):
            raise ValueError("archive contains a nonregular or unsafe member")
        manifest_bytes = archive.extractfile("MANIFEST.json").read()
        if hashlib.sha256(manifest_bytes).hexdigest() != EXPECTED_MANIFEST:
            raise ValueError("manifest identity differs")
        manifest = json.loads(manifest_bytes)
        expected = {row["path"]: row for row in manifest["files"]}
        names = [member.name for member in members]
        if len(names) != len(set(names)) or set(names) != set(expected) | {"MANIFEST.json"}:
            raise ValueError("member set differs")
        total = 0
        for name, row in expected.items():
            raw = archive.extractfile(name).read()
            if len(raw) != row["bytes"] or hashlib.sha256(raw).hexdigest() != row["sha256"]:
                raise ValueError("original member differs: " + name)
            total += len(raw)
        if len(expected) != 400 or total != manifest["raw_bytes"] or total != 95_978_279:
            raise ValueError("original member accounting differs")
    if args.output is not None:
        with args.output.open("xb") as output:
            output.write(data)
    print(json.dumps({"archive_sha256": EXPECTED_ARCHIVE,
                      "manifest_sha256": EXPECTED_MANIFEST,
                      "verified_original_files": 400,
                      "verified_original_bytes": 95_978_279,
                      "complete_NoUpdate": False}, indent=2))


if __name__ == "__main__":
    main()
