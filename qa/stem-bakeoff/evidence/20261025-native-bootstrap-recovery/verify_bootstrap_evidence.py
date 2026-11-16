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
assert len(data) == manifest["archive"]["bytes"]
assert hashlib.sha256(data).hexdigest() == manifest["archive"]["sha256"]
with tarfile.open(archive, "r:xz") as tar:
    members = tar.getmembers()
    names = [member.name for member in members]
    assert len(names) == len(set(names)), "duplicate archive entry"
    for name in names:
        path = PurePosixPath(name)
        assert not path.is_absolute() and ".." not in path.parts
    inventory_bytes = tar.extractfile("member-inventory.json").read()
    assert hashlib.sha256(inventory_bytes).hexdigest() == manifest["archive"]["member_inventory_sha256"]
    inventory = json.loads(inventory_bytes)
    assert set(names) == set(inventory) | {"member-inventory.json"}
    files, directories, retained_bytes = 0, 0, 0
    for member in members:
        if member.name == "member-inventory.json":
            continue
        expected = inventory[member.name]
        assert member.mode == expected["mode"], member.name
        if expected["kind"] == "directory":
            assert member.isdir(), member.name
            directories += 1
        else:
            assert member.isfile(), member.name
            contents = tar.extractfile(member).read()
            assert len(contents) == expected["bytes"], member.name
            assert hashlib.sha256(contents).hexdigest() == expected["sha256"], member.name
            files += 1
            retained_bytes += len(contents)
    assert files == manifest["archive"]["payload_files"]
    assert directories == manifest["archive"]["payload_directories"]
    assert retained_bytes == manifest["archive"]["payload_file_bytes"]
print(json.dumps({"archive_sha256": manifest["archive"]["sha256"], "payload_files": files, "payload_directories": directories, "payload_file_bytes": retained_bytes, "all_bytes_modes_verified": True, "sqlite_connections": 0, "tests_or_models_executed": 0}))
