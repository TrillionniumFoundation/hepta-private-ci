#!/usr/bin/env python3
"""Restore and verify original hosted artifacts; never execute their contents."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile


def require(ok, message):
    if not ok:
        raise ValueError(message)


def check(data, record):
    require(len(data) == record["bytes"] and hashlib.sha256(data).hexdigest() == record["sha256"], "size/hash mismatch")


def safe(name):
    path = Path(name)
    require(not path.is_absolute() and ".." not in path.parts, "unsafe member path")
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    rows = json.loads((root / "archives.json").read_text())["archives"]
    for row in rows:
        require(row["encoding"] == "ordered-binary-parts", "unknown archive encoding")
        parts = []
        for part in row["parts"]:
            content = (root / safe(part["path"])).read_bytes()
            check(content, part)
            parts.append(content)
        content = b"".join(parts)
        check(content, row)
        archive = args.output / safe(row["archive_name"])
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_bytes(content)
        with zipfile.ZipFile(archive) as z:
            require(z.testzip() is None, "ZIP CRC error")
            expected = {x["path"]: x for x in row["members"]}
            actual = [x.filename for x in z.infolist() if not x.is_dir()]
            require(len(actual) == len(set(actual)) and set(actual) == set(expected), "archive member set differs")
            for member in z.infolist():
                name = safe(member.filename)
                require((member.external_attr >> 16) & 0o170000 != 0o120000, "ZIP symlink")
                if member.is_dir():
                    continue
                raw = z.read(member)
                check(raw, expected[member.filename])
                target = archive.with_suffix("") / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
        print(json.dumps({"artifact_id": row["artifact_id"], "sha256": row["sha256"], "verified_members": len(row["members"])}))


if __name__ == "__main__":
    main()
