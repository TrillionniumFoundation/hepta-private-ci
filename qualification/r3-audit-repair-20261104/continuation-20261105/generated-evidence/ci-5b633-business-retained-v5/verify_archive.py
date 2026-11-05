#!/usr/bin/env python3
"""Verify the immutable original CI transport without running project code."""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile


def digest(data):
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "computed_git_blob": hashlib.sha1(
            f"blob {len(data)}\0".encode() + data
        ).hexdigest(),
    }


def verify(data, expected):
    actual = digest(data)
    if actual != expected:
        raise ValueError(f"Identity mismatch: {actual!r} != {expected!r}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, nargs="?", default=Path(__file__).parent)
    args = parser.parse_args()
    transport = json.loads((args.directory / "transport-manifest.json").read_bytes())
    original_bytes = (args.directory / transport["original_files_manifest"]["name"]).read_bytes()
    original_identity = dict(transport["original_files_manifest"])
    original_identity.pop("name")
    verify(original_bytes, original_identity)
    original = json.loads(original_bytes)
    chunks = []
    offset = 0
    parts = transport["parts"]
    assert len(parts) == transport["part_count"]
    assert len({p["name"] for p in parts}) == len(parts)
    for index, part in enumerate(parts):
        assert part["index"] == index and part["compressed_offset"] == offset
        name = PurePosixPath(part["name"])
        assert len(name.parts) == 1 and not name.is_absolute()
        encoded = (args.directory / str(name)).read_bytes()
        verify(encoded, part["file"])
        assert encoded.endswith(b"\n") and b"\n" not in encoded[:-1]
        decoded = base64.b64decode(encoded[:-1], validate=True)
        verify(decoded, part["decoded_chunk"])
        chunks.append(decoded)
        offset += len(decoded)
    archive = b"".join(chunks)
    archive_identity = dict(transport["archive"])
    archive_identity.pop("name")
    verify(archive, archive_identity)
    expected = {row["member"]: row for row in original["files"]}
    assert len(expected) == original["file_count"]
    total = 0
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        members = tar.getmembers()
        assert len(members) == len(expected)
        assert len({m.name for m in members}) == len(members)
        assert {m.name for m in members} == set(expected)
        for member in members:
            path = PurePosixPath(member.name)
            assert member.isfile() and not path.is_absolute() and ".." not in path.parts
            stream = tar.extractfile(member)
            assert stream is not None
            data = stream.read()
            identity = dict(expected[member.name])
            identity.pop("member")
            verify(data, identity)
            assert member.size == len(data)
            total += len(data)
    assert total == original["total_original_bytes"]
    print(json.dumps({
        "transport_parts": len(parts), "original_files": len(expected),
        "original_bytes": total, "archive": digest(archive),
        "all_part_and_original_identities_verified": True,
        "project_commands_executed": False,
    }, indent=2))


if __name__ == "__main__":
    main()
