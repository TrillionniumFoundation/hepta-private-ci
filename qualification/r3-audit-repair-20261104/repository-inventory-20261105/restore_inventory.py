#!/usr/bin/env python3
"""Verify the frozen inventory archive and optionally restore its exact JSON."""

import argparse
import base64
import gzip
import hashlib
import io
import json
from pathlib import Path
from pathlib import PurePosixPath
import tarfile


def identity(data):
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "blob": hashlib.sha1(
            b"blob " + str(len(data)).encode() + b"\0" + data
        ).hexdigest(),
    }


def check_identity(data, expected):
    actual = identity(data)
    for key, value in actual.items():
        if expected.get(key) != value:
            raise ValueError(f"Identity mismatch for {key}: {value}")
    return actual


def safe_file(directory, name):
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"Invalid archive part path: {name}")
    local = directory / path
    local.resolve().relative_to(directory.resolve())
    if local.is_symlink() or not local.is_file():
        raise ValueError(f"Not a regular archive part: {name}")
    return local


def restore(directory):
    index = json.loads(
        (directory.parent / "fourth-repository-inventory-20261105.json").read_bytes()
    )
    if index.get("schema") != "hepta.frozen-repository-inventory-index.v1":
        raise ValueError("Expected the typed frozen inventory index")
    manifest_bytes = (directory / "archive-manifest.json").read_bytes()
    check_identity(manifest_bytes, index["archive"]["manifest_identity"])
    manifest = json.loads(manifest_bytes)
    encoded_parts = []
    offset = 0
    for number, part in enumerate(manifest["parts"]):
        if part["sequence"] != number or part["offset"] != offset:
            raise ValueError("Archive parts are not contiguous")
        data = safe_file(directory, part["path"]).read_bytes()
        check_identity(data, part)
        encoded_parts.append(data)
        offset += len(data)
    if len(encoded_parts) != index["archive"]["part_count"]:
        raise ValueError("Unexpected archive part count")
    if offset != manifest["base64_bytes"]:
        raise ValueError("Incomplete encoded archive")
    compressed = base64.b64decode(b"".join(encoded_parts), validate=True)
    check_identity(compressed, manifest["gzip"])
    uncompressed = gzip.decompress(compressed)
    check_identity(uncompressed, manifest["uncompressed_tar"])
    expected = {row["path"]: row for row in manifest["members"]}
    if len(expected) != manifest["member_count"]:
        raise ValueError("Duplicate expected archive members")
    inventory_bytes = None
    with tarfile.open(fileobj=io.BytesIO(uncompressed), mode="r:") as archive:
        members = archive.getmembers()
        if len(members) != len(expected):
            raise ValueError("Unexpected archive member count")
        if {member.name for member in members} != set(expected):
            raise ValueError("Unexpected archive member names")
        for member in members:
            path = PurePosixPath(member.name)
            if not member.isfile() or path.is_absolute() or ".." in path.parts:
                raise ValueError(f"Unsafe archive member: {member.name}")
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError(f"Unreadable archive member: {member.name}")
            data = stream.read()
            check_identity(data, expected[member.name])
            if len(data) != member.size:
                raise ValueError(f"Incomplete archive member: {member.name}")
            if member.name == index["archive"]["inventory_member"]:
                inventory_bytes = data
    if inventory_bytes is None:
        raise ValueError("The complete inventory member is absent")
    check_identity(inventory_bytes, index["original"])
    check_identity(inventory_bytes, manifest["inventory"])
    inventory = json.loads(inventory_bytes)
    if inventory.get("schema") != index["original"]["schema"]:
        raise ValueError("Unexpected restored inventory schema")
    if inventory["counts"] != index["counts"]:
        raise ValueError("The frozen count projection differs from the original")
    if len(inventory["prs"]) != index["counts"]["open_prs"]:
        raise ValueError("The complete PR list differs from the frozen count")
    return inventory_bytes, index, len(members)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    data, index, member_count = restore(Path(__file__).resolve().parent)
    if args.output is not None:
        with args.output.open("xb") as output:
            output.write(data)
    print(json.dumps({
        "complete_original_identity": identity(data),
        "archive_parts_verified": index["archive"]["part_count"],
        "all_archive_members_verified": member_count,
        "complete_gzip_crc_verified": True,
        "counts": index["counts"],
        "output": str(args.output) if args.output is not None else None,
        "scope": "Frozen evidence verification; no project tests or ref changes.",
    }, indent=2))


if __name__ == "__main__":
    main()
