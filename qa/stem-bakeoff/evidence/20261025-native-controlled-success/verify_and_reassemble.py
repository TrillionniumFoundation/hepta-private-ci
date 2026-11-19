"""Verify ordered parts, reconstruct the archive, and read every regular member."""

from pathlib import Path
import argparse
import hashlib
import json
import tarfile

parser = argparse.ArgumentParser()
parser.add_argument("manifest", type=Path)
parser.add_argument("--output", type=Path)
args = parser.parse_args()
manifest = json.loads(args.manifest.read_bytes())
root = args.manifest.resolve().parent
output = args.output or root / (manifest["archive"]["filename"] + ".reassembled")
digest = hashlib.sha256()
total = 0
with output.open("xb") as target:
    for row in manifest["parts"]:
        if not (Path(row["filename"]).name == row["filename"]):
            raise ValueError("archive integrity check failed")
        data = (root / row["filename"]).read_bytes()
        if not (len(data) == row["bytes"] <= 5 * 1024 * 1024):
            raise ValueError("archive integrity check failed")
        if not (hashlib.sha256(data).hexdigest() == row["sha256"]):
            raise ValueError("archive integrity check failed")
        target.write(data)
        digest.update(data)
        total += len(data)
if not (total == manifest["archive"]["bytes"]):
    raise ValueError("archive integrity check failed")
if not (digest.hexdigest() == manifest["archive"]["sha256"]):
    raise ValueError("archive integrity check failed")
with tarfile.open(output, "r:xz") as archive:
    members = archive.getmembers()
    if not (len({member.name for member in members}) == len(members)):
        raise ValueError("archive integrity check failed")
    if not (
        all(
            not member.name.startswith("/") and ".." not in Path(member.name).parts
            for member in members
        )
    ):
        raise ValueError("archive integrity check failed")
    if not (all(member.isfile() or member.isdir() for member in members)):
        raise ValueError("archive integrity check failed")
    index_data = archive.extractfile("audit/member-inventory.json").read()
    if not (
        hashlib.sha256(index_data).hexdigest()
        == manifest["archive"]["member_inventory_sha256"]
    ):
        raise ValueError("archive integrity check failed")
    index = json.loads(index_data)
    regular = [member for member in members if member.isfile()]
    if not (len(regular) == manifest["archive"]["regular_members"]):
        raise ValueError("archive integrity check failed")
    if not (len(members) - len(regular) == manifest["archive"]["directory_members"]):
        raise ValueError("archive integrity check failed")
    if not (
        {member.name for member in regular}
        == set(index) | {"audit/member-inventory.json"}
    ):
        raise ValueError("archive integrity check failed")
    for member in regular:
        if member.name == "audit/member-inventory.json":
            continue
        row = index[member.name]
        data = archive.extractfile(member).read()
        if not (len(data) == row["bytes"]):
            raise ValueError("archive integrity check failed")
        if not (hashlib.sha256(data).hexdigest() == row["sha256"]):
            raise ValueError("archive integrity check failed")
        if not (member.mode == row["mode"]):
            raise ValueError("archive integrity check failed")
    for label, expected in manifest["raw_runs"].items():
        before = archive.extractfile(f"audit/{label}-inventory-before.json").read()
        after = archive.extractfile(f"audit/{label}-inventory-after.json").read()
        if not (before == after):
            raise ValueError("archive integrity check failed")
        raw = json.loads(before)
        actual = [
            member for member in regular if member.name.startswith(f"runs/{label}/")
        ]
        if not (len(actual) == expected["files"]):
            raise ValueError("archive integrity check failed")
        if not (sum(member.size for member in actual) == expected["bytes"]):
            raise ValueError("archive integrity check failed")
        for name, row in raw.items():
            tar_name = f"runs/{label}" if name == "." else f"runs/{label}/{name}"
            member = archive.getmember(tar_name)
            if not (member.mode == int(row["mode"], 8)):
                raise ValueError("archive integrity check failed")
            if row["type"] == "directory":
                if not (member.isdir()):
                    raise ValueError("archive integrity check failed")
            else:
                if not (member.isfile()):
                    raise ValueError("archive integrity check failed")
                if not (
                    hashlib.sha256(archive.extractfile(member).read()).hexdigest()
                    == row["sha256"]
                ):
                    raise ValueError("archive integrity check failed")
result = dict(
    archive_sha256=digest.hexdigest(),
    archive_bytes=total,
    verified_parts=len(manifest["parts"]),
    regular_members=len(regular),
    directory_members=len(members) - len(regular),
    all_member_bytes_and_modes_verified=True,
    raw_run_before_after_inventory_equal=True,
    raw_original_files=sum(row["files"] for row in manifest["raw_runs"].values()),
    raw_original_bytes=sum(row["bytes"] for row in manifest["raw_runs"].values()),
    extraction_performed=False,
    model_calls=0,
    rust_runs=0,
    sqlite_connections=0,
)
print(json.dumps(result, sort_keys=True))
