"""Verify archive bytes and every retained file/mode without executing fixtures."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile


parser = argparse.ArgumentParser()
parser.add_argument("manifest", type=Path)
args = parser.parse_args()
manifest = json.loads(args.manifest.read_bytes())
archive = args.manifest.parent / manifest["archive"]["file"]
data = archive.read_bytes()
if not (len(data) == manifest["archive"]["bytes"]):
    raise ValueError("archive integrity check failed")
if not (hashlib.sha256(data).hexdigest() == manifest["archive"]["sha256"]):
    raise ValueError("archive integrity check failed")
with tarfile.open(archive, "r:xz") as tar:
    members = tar.getmembers()
    names = [member.name for member in members]
    if not (len(names) == len(set(names))):
        raise ValueError("duplicate archive entry")
    for name in names:
        path = PurePosixPath(name)
        if not (not path.is_absolute() and ".." not in path.parts):
            raise ValueError("archive integrity check failed")
    inventory_bytes = tar.extractfile("member-inventory.json").read()
    if not (
        hashlib.sha256(inventory_bytes).hexdigest()
        == manifest["archive"]["member_inventory_sha256"]
    ):
        raise ValueError("archive integrity check failed")
    inventory = json.loads(inventory_bytes)
    if not (set(names) == set(inventory) | {"member-inventory.json"}):
        raise ValueError("archive integrity check failed")
    files, directories, retained_bytes = 0, 0, 0
    for member in members:
        if member.name == "member-inventory.json":
            continue
        expected = inventory[member.name]
        if not (member.mode == expected["mode"]):
            raise ValueError(member.name)
        if expected["kind"] == "directory":
            if not (member.isdir()):
                raise ValueError(member.name)
            directories += 1
        else:
            if not (member.isfile()):
                raise ValueError(member.name)
            contents = tar.extractfile(member).read()
            if not (len(contents) == expected["bytes"]):
                raise ValueError(member.name)
            if not (hashlib.sha256(contents).hexdigest() == expected["sha256"]):
                raise ValueError(member.name)
            files += 1
            retained_bytes += len(contents)
    if not (files == manifest["archive"]["payload_files"]):
        raise ValueError("archive integrity check failed")
    if not (directories == manifest["archive"]["payload_directories"]):
        raise ValueError("archive integrity check failed")
    if not (retained_bytes == manifest["archive"]["payload_file_bytes"]):
        raise ValueError("archive integrity check failed")
print(
    json.dumps(
        {
            "archive_sha256": manifest["archive"]["sha256"],
            "payload_files": files,
            "payload_directories": directories,
            "payload_file_bytes": retained_bytes,
            "all_bytes_modes_verified": True,
            "sqlite_connections": 0,
            "tests_or_models_executed": 0,
        }
    )
)
