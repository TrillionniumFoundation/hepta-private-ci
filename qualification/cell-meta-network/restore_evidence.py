"""Restore and verify a complete structural experiment evidence archive."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def restore(archive_directory, destination):
    manifest = json.loads((archive_directory / "ARCHIVE.json").read_text())
    if manifest["schema"] != "hepta.evidence.archive.v1":
        raise ValueError("unsupported archive schema")
    if destination.exists():
        raise ValueError("destination must be new")
    chunks = []
    for part in manifest["parts"]:
        name = Path(part["path"])
        if name.is_absolute() or len(name.parts) != 1:
            raise ValueError("invalid part path")
        raw = (archive_directory / name).read_bytes()
        if len(raw) != part["bytes"] or digest(raw) != part["sha256"]:
            raise ValueError(f"part checksum mismatch: {name}")
        chunks.append(raw)
    raw = b"".join(chunks)
    if len(raw) != manifest["archive_bytes"] or digest(raw) != manifest["archive_sha256"]:
        raise ValueError("archive checksum mismatch")
    expected = {item["path"]: item for item in manifest["members"]}
    if len(expected) != len(manifest["members"]):
        raise ValueError("duplicate manifest path")
    verified = []
    seen = set()
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:xz") as archive:
        for member in archive:
            path = Path(member.name)
            if (not member.isfile() or path.is_absolute() or ".." in path.parts
                    or member.name in seen or member.name not in expected):
                raise ValueError(f"invalid archive member: {member.name}")
            entry = expected[member.name]
            if member.size != entry["bytes"]:
                raise ValueError(f"member length mismatch: {member.name}")
            data = archive.extractfile(member).read()
            if digest(data) != entry["sha256"]:
                raise ValueError(f"member checksum mismatch: {member.name}")
            seen.add(member.name)
            verified.append((path, data))
    if seen != expected.keys():
        raise ValueError("missing archive members")
    destination.mkdir(parents=True)
    for path, data in verified:
        output = destination / path
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(data)
    return {"verified_members": len(verified), "archive_sha256": digest(raw),
            "restored_bytes": sum(len(data) for _, data in verified)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive_directory", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(json.dumps(restore(args.archive_directory, args.destination), indent=2))
