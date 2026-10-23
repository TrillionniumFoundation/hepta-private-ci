#!/usr/bin/env python3
"""Bound every auxiliary evidence file; never infer execution or owner authority.

The receipt and its checksum are the only excluded root files, avoiding a hash
cycle. Archive mode copies completed mutation evidence, not build targets or
source worktrees. The qualified source is never written.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat

SCHEMA = "hepta.cognitive-types.evidence-files.v1"
EXCLUDED = frozenset(("receipt.json", "receipt.sha256"))
MAX_ENTRIES = 1024
MAX_DEPTH = 16
MAX_PATH_BYTES = 512
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024
SHA256 = re.compile(r"[0-9a-f]{64}")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def safe_relative(value: object) -> str:
    require(isinstance(value, str) and bool(value), "missing evidence path")
    path = PurePosixPath(value)
    require(not path.is_absolute() and str(path) == value
            and all(part not in ("", ".", "..") for part in path.parts)
            and "\\" not in value and "\0" not in value
            and len(value.encode("utf-8")) <= MAX_PATH_BYTES, "unsafe evidence path")
    return value


def fingerprint(info: os.stat_result) -> tuple:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def hash_regular_file(path: Path, expected: os.stat_result, maximum: int) -> tuple[int, str]:
    require(stat.S_ISREG(expected.st_mode), "nonregular evidence file")
    require(expected.st_size <= maximum, "evidence byte budget exceeded")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    digest = hashlib.sha256()
    size = 0
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and fingerprint(before) == fingerprint(expected),
                "evidence changed before hashing")
        while chunk := stream.read(min(CHUNK_BYTES, maximum - size + 1)):
            size += len(chunk)
            require(size <= maximum, "evidence byte budget exceeded")
            digest.update(chunk)
        require(fingerprint(os.fstat(stream.fileno())) == fingerprint(before)
                and size == before.st_size, "evidence changed while hashing")
    require(fingerprint(path.lstat()) == fingerprint(before), "evidence path changed while hashing")
    return size, digest.hexdigest()


def collect_inventory(directory: Path) -> dict:
    require(not directory.is_symlink() and directory.is_dir(), "missing or symlinked evidence directory")
    files = []
    total = 0
    entries = 0

    def visit(current: Path, depth: int) -> None:
        nonlocal total, entries
        require(depth <= MAX_DEPTH, "evidence nesting limit exceeded")
        before = current.lstat()
        require(stat.S_ISDIR(before.st_mode), "non-directory evidence path")
        with os.scandir(current) as iterator:
            for item in iterator:
                path = Path(item.path)
                relative = safe_relative(path.relative_to(directory).as_posix())
                if relative not in EXCLUDED:
                    entries += 1
                    require(entries <= MAX_ENTRIES, "evidence entry budget exceeded")
                info = path.lstat()
                # Even the two excluded sidecars cannot be links or devices.
                require(not stat.S_ISLNK(info.st_mode), "symlinked evidence is forbidden")
                if stat.S_ISDIR(info.st_mode):
                    require(relative not in EXCLUDED, "receipt sidecar is a directory")
                    visit(path, depth + 1)
                else:
                    require(stat.S_ISREG(info.st_mode), "nonregular evidence file")
                    if relative not in EXCLUDED:
                        size, digest = hash_regular_file(path, info, MAX_TOTAL_BYTES - total)
                        total += size
                        files.append({"path": relative, "bytes": size, "sha256": digest})
        require(fingerprint(current.lstat()) == fingerprint(before), "evidence directory changed while hashing")

    visit(directory, 0)
    files.sort(key=lambda row: row["path"])
    return {"schema": SCHEMA, "total_bytes": total, "files": files}


def verify_inventory(directory: Path, expected: object) -> dict:
    require(isinstance(expected, dict) and set(expected) == {"schema", "total_bytes", "files"}
            and expected.get("schema") == SCHEMA, "missing or invalid evidence inventory")
    require(type(expected["total_bytes"]) is int and 0 <= expected["total_bytes"] <= MAX_TOTAL_BYTES,
            "invalid evidence total size")
    rows = expected["files"]
    require(isinstance(rows, list) and len(rows) <= MAX_ENTRIES, "invalid evidence inventory entries")
    names = []
    for row in rows:
        require(isinstance(row, dict) and set(row) == {"path", "bytes", "sha256"}, "invalid evidence file row")
        names.append(safe_relative(row["path"]))
        require(names[-1] not in EXCLUDED, "self-referential receipt inventory")
        require(type(row["bytes"]) is int and 0 <= row["bytes"] <= MAX_TOTAL_BYTES, "invalid evidence file size")
        require(isinstance(row["sha256"], str) and SHA256.fullmatch(row["sha256"]) is not None,
                "invalid evidence file digest")
    require(names == sorted(set(names)), "duplicate or noncanonical evidence inventory")
    require(sum(row["bytes"] for row in rows) == expected["total_bytes"], "evidence total size mismatch")
    observed = collect_inventory(directory)
    require(observed == expected, "missing, added or modified auxiliary evidence")
    return observed


def require_files(inventory: dict, names: list[str]) -> None:
    available = {row["path"] for row in inventory["files"]}
    require(set(names) <= available, "required command or auxiliary evidence is missing")


def require_fresh_output(directory: Path) -> None:
    require(not directory.is_symlink(), "output directory cannot be a symlink")
    if directory.exists():
        require(directory.is_dir() and next(directory.iterdir(), None) is None,
                "refusing to overwrite or reuse existing evidence")


def archive(source: Path, destination: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    for path in (source, destination):
        require(not path.is_symlink(), "archive paths cannot be symlinks")
        resolved = path.resolve()
        require(resolved != root and root not in resolved.parents and resolved not in root.parents,
                "evidence archive must be disjoint from source")
    left, right = source.resolve(), destination.resolve()
    require(left != right and left not in right.parents and right not in left.parents,
            "archive source and destination must be disjoint")
    require(not destination.exists(), "archive destination already exists")
    manifest = collect_inventory(source)
    require_files(manifest, ["mutation-receipt.json"])
    # Preserve links instead of following them if a source changes mid-copy;
    # the post-copy inventory will reject them. An error never deletes evidence.
    shutil.copytree(source, destination, symlinks=True)
    verify_inventory(destination, manifest)
    verify_inventory(source, manifest)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    archive(args.archive, args.destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
