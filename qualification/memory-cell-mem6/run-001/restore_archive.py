#!/usr/bin/env python3
"""Verify and restore the pinned MEM6 CAS archive using Python's standard library.

Usage: python restore_archive.py --archive mem6-cas-001.tar.xz \
    --destination /new/restored --receipt /existing/RESTORE_RECEIPT.json

Both output paths must be absent and their parents must already exist. All
archive members are verified before the destination is created. An interrupted
restore may leave an incomplete destination; it is never reused or overwritten.
No archived code is executed, and file permissions/timestamps are not replayed.
This verifies archive bytes, not owner recovery or an independent trust domain.
The filesystem owner and output parent directories must be trusted; this does
not protect against a malicious owner changing files during or after restore.
"""

import argparse
import hashlib
import json
import lzma
import os
from pathlib import Path
import re
import stat
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
import unicodedata


EXPECTED = {
    "archive_bytes": 61412948,
    "archive_sha256": "f77acd9feb27fda3f8000b0d089dbdbe258a4adfb7acedcb2e0cd590cc4f361e",
    "manifest_sha256": "3c7799846836a18b6a5470e03cda92919ede2fcf76c8ee9ede20ae0e945ce336",
    "file_count": 10365,
    "logical_bytes": 243281645,
    "source_commit": "8cf848babdd897e9f38642d5faf3ba0f72a1303c",
}
BLOCK = 1024 * 1024
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
HASH = re.compile(r"[0-9a-f]{64}\Z")
WINDOWS_DEVICES = {"con", "prn", "aux", "nul"} | {
    f"{prefix}{number}" for prefix in ("com", "lpt") for number in range(1, 10)
}


class RestoreError(ValueError):
    """An input or output violates the archive restoration contract."""


def _require(condition, message):
    if not condition:
        raise RestoreError(message)


def _read_exact(stream, size):
    data = stream.read(size)
    _require(len(data) == size, "truncated archive member or header")
    return data


def _copy_exact(source, target, size):
    digest = hashlib.sha256()
    remaining = size
    while remaining:
        chunk = _read_exact(source, min(BLOCK, remaining))
        digest.update(chunk)
        if target is not None:
            target.write(chunk)
        remaining -= len(chunk)
    return digest.hexdigest()


def _unique_json(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _logical_path(value):
    _require(isinstance(value, str) and 0 < len(value) <= 4096, "invalid logical path")
    _require(not any(ord(c) < 32 or ord(c) == 127 for c in value), "control in path")
    _require(not any(c in value for c in '\\:*?"<>|'), f"unsafe path: {value!r}")
    parts = value.split("/")
    for part in parts:
        _require(part not in ("", ".", ".."), f"non-relative or non-canonical path: {value!r}")
        _require(len(part.encode("utf-8")) <= 255, "oversized path component")
        _require(not part.endswith((" ", ".")), f"non-portable path: {value!r}")
        _require(part.split(".", 1)[0].casefold() not in WINDOWS_DEVICES, "reserved path")
    return parts


def _parse_manifest(raw, expected):
    _require(hashlib.sha256(raw).hexdigest() == expected["manifest_sha256"], "manifest SHA256 mismatch")
    manifest = json.loads(raw, object_pairs_hook=_unique_json)
    _require(isinstance(manifest, dict), "manifest must be an object")
    _require(manifest.get("schema") == "hepta.mem6.raw-archive.v1", "unexpected manifest schema")
    _require(manifest.get("source_commit") == expected["source_commit"], "source commit mismatch")
    for flag in ("external_runtime_inputs_included", "full_owner_cold_recovery", "independent_trust_domain"):
        _require(manifest.get(flag) is False, f"unexpected manifest claim: {flag}")
    rows = manifest.get("files")
    _require(isinstance(rows, list) and len(rows) == expected["file_count"], "file count mismatch")
    _require(type(manifest.get("file_count")) is int, "invalid declared file count")
    _require(manifest["file_count"] == len(rows), "declared file count mismatch")
    objects, paths, spellings = {}, set(), {}
    total = 0
    for row in rows:
        _require(isinstance(row, dict) and set(row) == {"path", "sha256", "bytes"}, "invalid file row")
        parts = _logical_path(row["path"])
        _require(row["path"] not in paths, f"duplicate logical path: {row['path']!r}")
        paths.add(row["path"])
        for end in range(1, len(parts) + 1):
            original = "/".join(parts[:end])
            canonical = unicodedata.normalize("NFC", original).casefold()
            _require(spellings.get(canonical, original) == original, "case or Unicode path collision")
            spellings[canonical] = original
        size, digest = row["bytes"], row["sha256"]
        _require(type(size) is int and size >= 0, "invalid file byte count")
        _require(isinstance(digest, str) and HASH.fullmatch(digest), "invalid object SHA256")
        _require(objects.get(digest, size) == size, "conflicting sizes for one object")
        objects[digest] = size
        total += size
        _require(total <= expected["logical_bytes"], "logical byte budget exceeded")
    for path in paths:
        parts = path.split("/")
        _require(not any("/".join(parts[:n]) in paths for n in range(1, len(parts))), "file/directory path collision")
    _require(type(manifest.get("total_bytes")) is int, "invalid declared logical bytes")
    _require(total == manifest["total_bytes"] == expected["logical_bytes"], "logical byte total mismatch")
    _require(manifest.get("source_capsule_included") in paths, "source capsule missing from manifest")
    return manifest, objects


def _verify_members(compressed, spool, expected):
    """Parse every header explicitly, including data after tar end markers."""
    seen, object_sizes = set(), {}
    manifest, manifest_bytes = None, 0
    with lzma.LZMAFile(compressed, "rb") as stream:
        while True:
            header = _read_exact(stream, 512)
            if header == bytes(512):
                _require(_read_exact(stream, 512) == bytes(512), "missing second tar end marker")
                trailing = stream.read(10241)
                _require(len(trailing) <= 10240 and not any(trailing), "unexpected data after tar end markers")
                _require(not stream.read(1), "oversized tar trailer")
                break
            member = tarfile.TarInfo.frombuf(header, "utf-8", "strict")
            _require(member.type in (tarfile.REGTYPE, tarfile.AREGTYPE), "only regular tar members allowed")
            _require(not member.linkname and not member.sparse, "links and sparse members forbidden")
            _require(member.name not in seen, f"duplicate tar member: {member.name!r}")
            seen.add(member.name)
            if manifest is None:
                _require(member.name == "MANIFEST.json", "manifest must be the first member")
                _require(0 < member.size <= MAX_MANIFEST_BYTES, "invalid manifest size")
                raw = _read_exact(stream, member.size)
                manifest, object_sizes = _parse_manifest(raw, expected)
                manifest_bytes = member.size
            else:
                _require(member.name.startswith("objects/"), "unexpected tar member path")
                digest = member.name[len("objects/"):]
                _require(HASH.fullmatch(digest) and digest in object_sizes, "unknown or unsafe object member")
                _require(member.size == object_sizes[digest], "object byte count mismatch")
                with (spool / digest).open("xb") as target:
                    actual = _copy_exact(stream, target, member.size)
                _require(actual == digest, f"object SHA256 mismatch: {digest}")
            padding = _read_exact(stream, (-member.size) % 512)
            _require(not any(padding), "nonzero tar member padding")
        _require(manifest is not None, "manifest absent")
        expected_members = {"MANIFEST.json"} | {f"objects/{digest}" for digest in object_sizes}
        _require(seen == expected_members, "missing or extra CAS objects")
    return manifest, manifest_bytes, object_sizes


def _absent_output(path):
    value = Path(path).expanduser()
    _require(value.name not in ("", ".", ".."), "invalid output path")
    parent = value.parent.resolve(strict=True)
    _require(parent.is_dir(), "output parent must be an existing directory")
    result = parent / value.name
    _require(not result.exists() and not result.is_symlink(), f"output already exists: {result}")
    return result


def restore_archive(archive, destination, receipt, *, expected=EXPECTED):
    """Restore bytes against an explicit trusted descriptor; the CLI pins MEM6."""
    destination = _absent_output(destination)
    receipt = _absent_output(receipt)
    _require(destination != receipt, "destination and receipt must be distinct")
    archive = Path(archive).expanduser()
    _require(stat.S_ISREG(archive.lstat().st_mode), "archive must be a regular file, not a symlink")
    with archive.open("rb") as source, tempfile.TemporaryDirectory(prefix="mem6-restore-") as temporary:
        _require(os.fstat(source.fileno()).st_size == expected["archive_bytes"], "archive byte count mismatch")
        actual = _copy_exact(source, None, expected["archive_bytes"])
        _require(not source.read(1) and actual == expected["archive_sha256"], "archive SHA256 mismatch")
        source.seek(0)
        spool = Path(temporary)
        manifest, manifest_bytes, objects = _verify_members(source, spool, expected)
        destination.mkdir(mode=0o700, exist_ok=False)
        for row in manifest["files"]:
            target = destination.joinpath(*row["path"].split("/"))
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with (spool / row["sha256"]).open("rb") as stored, target.open("xb") as output:
                digest = _copy_exact(stored, output, row["bytes"])
                _require(not stored.read(1), "spooled object has unexpected suffix")
            _require(digest == row["sha256"] and target.stat().st_size == row["bytes"], "restored file verification failed")
            with target.open("rb") as restored:
                digest = _copy_exact(restored, None, row["bytes"])
                _require(not restored.read(1) and digest == row["sha256"], "restored file readback SHA256 mismatch")
        result = {
            "schema": "hepta.mem6.archive-restore-receipt.v1",
            "status": "verified",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "archive": {"path": str(archive.resolve()), "bytes": expected["archive_bytes"], "sha256": actual},
            "manifest": {"schema": manifest["schema"], "bytes": manifest_bytes, "sha256": expected["manifest_sha256"], "source_commit": manifest["source_commit"]},
            "destination": str(destination),
            "logical_files_verified": len(manifest["files"]),
            "logical_bytes_verified": sum(row["bytes"] for row in manifest["files"]),
            "unique_objects_verified": len(objects),
            "unique_object_bytes_verified": sum(objects.values()),
            "checks": {
                "whole_archive_sha256": True,
                "manifest_sha256": True,
                "strict_member_paths_types_and_duplicates": True,
                "exact_object_set_and_each_object_bytes_sha256": True,
                "logical_path_collisions": True,
                "exclusive_new_destination": True,
                "each_restored_file_bytes_sha256": True,
            },
            "source_capsule_included": manifest["source_capsule_included"],
            "excluded_top_level": manifest["excluded_top_level"],
            "external_runtime_inputs_included": False,
            "full_owner_cold_recovery": False,
            "independent_trust_domain": False,
            "archived_runtime_executed": False,
            "scientific_benefit_inferred": False,
            "limitations": [
                "Archive byte restoration is not full owner or system capability cold recovery.",
                "External runtime inputs, live owners, authority state, and real effect state are not recovered here.",
                "The local filesystem owner and output parents are trusted; malicious owner races and later modification are outside this check.",
                "Hashes establish consistency with the supplied descriptor, not independent authorship or an independent trust domain.",
            ],
        }
        with receipt.open("x", encoding="utf-8", newline="\n") as output:
            json.dump(result, output, indent=2, sort_keys=True)
            output.write("\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = restore_archive(args.archive, args.destination, args.receipt)
    except (OSError, ValueError, tarfile.TarError, lzma.LZMAError) as exc:
        print(f"RESTORE FAILED: {exc}", file=sys.stderr)
        print("Any incomplete destination is retained; this tool never overwrites or resumes it.", file=sys.stderr)
        return 1
    print(json.dumps({key: result[key] for key in ("status", "destination", "logical_files_verified", "logical_bytes_verified", "unique_objects_verified")}, sort_keys=True))
    print(f"Receipt: {args.receipt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
