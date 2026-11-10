#!/usr/bin/env python3
"""Independently read back MEM6 restored files against the frozen archive manifest.

This is a read-only post-restoration audit, not an owner/authority recovery.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tarfile

ARCHIVE_SHA = "f77acd9feb27fda3f8000b0d089dbdbe258a4adfb7acedcb2e0cd590cc4f361e"
MANIFEST_SHA = "3c7799846836a18b6a5470e03cda92919ede2fcf76c8ee9ede20ae0e945ce336"
SOURCE_SHA = "8cf848babdd897e9f38642d5faf3ba0f72a1303c"
EXPECTED_FILES = 10365
EXPECTED_BYTES = 243281645


def sha256_path(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audit(archive, root):
    start = datetime.now(timezone.utc).isoformat()
    assert archive.is_file() and not archive.is_symlink()
    assert archive.stat().st_size == 61412948
    assert sha256_path(archive) == ARCHIVE_SHA
    assert root.is_dir() and not root.is_symlink()
    with tarfile.open(archive, mode="r:xz") as packed:
        first = packed.next()
        assert first is not None and first.name == "MANIFEST.json" and first.isfile()
        assert 0 < first.size < 8 * 1024 * 1024
        source = packed.extractfile(first)
        assert source is not None
        raw = source.read()
        assert len(raw) == first.size
    assert hashlib.sha256(raw).hexdigest() == MANIFEST_SHA
    manifest = json.loads(raw)
    assert manifest["source_commit"] == SOURCE_SHA
    rows = manifest["files"]
    assert len(rows) == EXPECTED_FILES
    expected_paths = set()
    total = 0
    catalog = hashlib.sha256()
    for row in rows:
        relative = PurePosixPath(row["path"])
        assert not relative.is_absolute() and relative.parts
        assert all(part not in ("", ".", "..") for part in relative.parts)
        assert row["path"] not in expected_paths
        expected_paths.add(row["path"])
        target = root.joinpath(*relative.parts)
        info = target.lstat()
        assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1
        assert info.st_size == row["bytes"]
        actual_hash = sha256_path(target)
        assert actual_hash == row["sha256"], row["path"]
        total += info.st_size
        catalog.update(f'{row["path"]}\0{row["bytes"]}\0{actual_hash}\n'.encode("utf-8"))
    assert total == EXPECTED_BYTES
    actual_paths = set()
    for folder, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            item = Path(folder) / name
            mode = item.lstat().st_mode
            assert stat.S_ISDIR(mode) or stat.S_ISREG(mode)
            if stat.S_ISREG(mode):
                actual_paths.add(item.relative_to(root).as_posix())
    assert actual_paths == expected_paths
    return {
        "schema": "hepta.mem6.independent-restored-file-readback.v1",
        "status": "verified",
        "started_at": start,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "archive": str(archive),
        "archive_sha256": ARCHIVE_SHA,
        "manifest_sha256": MANIFEST_SHA,
        "frozen_source_commit": SOURCE_SHA,
        "root": str(root),
        "verified_files": len(actual_paths),
        "verified_bytes": total,
        "ordered_manifest_catalog_sha256": catalog.hexdigest(),
        "no_extra_regular_files": True,
        "no_symlinks_or_special_nodes": True,
        "all_files_independently_sha256_checked": True,
        "full_owner_recovery": False,
        "independent_trust_domain": False,
        "scientific_acceptance": "HOLD",
        "adoption": "NoUpdate",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    assert not args.receipt.exists()
    result = audit(args.archive, args.root)
    with args.receipt.open("x", encoding="utf-8") as output:
        json.dump(result, output, indent=2, sort_keys=True)
        output.write("\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
