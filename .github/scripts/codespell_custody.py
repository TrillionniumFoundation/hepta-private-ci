#!/usr/bin/env python3
"""Verify exact archived bytes before excluding them from spelling checks.

This grants no execution or scientific qualification to the preserved sources.
The CI workflow validates again after Codespell to detect worktree drift.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys

MANIFEST = ".github/codespell-custody.json"
SCHEMA = "hepta.codespell-custody.v1"
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_SOURCE_BYTES = 8 * 1024 * 1024


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def file_identity(value):
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
        value.st_mode,
        value.st_nlink,
    )


def read_regular(root, relative, limit):
    path = root / relative
    for part in PurePosixPath(relative).parents:
        if (root / part).is_symlink():
            raise ValueError("symbolic link in archive path")
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise ValueError("archive input must be a regular single-link file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(path, flags), "rb") as handle:
        opened = os.fstat(handle.fileno())
        if file_identity(before) != file_identity(opened):
            raise ValueError("archive input changed before reading")
        data = handle.read(limit + 1)
        after = os.fstat(handle.fileno())
    if len(data) > limit:
        raise ValueError("archive input exceeds the byte limit")
    if file_identity(opened) != file_identity(after):
        raise ValueError("archive input changed while reading")
    if file_identity(after) != file_identity(path.lstat()):
        raise ValueError("archive path changed while reading")
    return data


def parse_manifest(raw):
    document = json.loads(raw, object_pairs_hook=unique_object)
    if (
        not isinstance(document, dict)
        or set(document) != {"schema", "files"}
        or document["schema"] != SCHEMA
        or not isinstance(document["files"], dict)
        or not document["files"]
    ):
        raise ValueError("invalid Codespell custody manifest")
    entries = document["files"]
    for path, expected in entries.items():
        if (
            not isinstance(path, str)
            or not re.fullmatch(r"library-recovery/[A-Za-z0-9._/-]+", path)
            or str(PurePosixPath(path)) != path
            or any(part in {".", ".."} for part in path.split("/"))
            or len(PurePosixPath(path).parts) < 3
        ):
            raise ValueError("archive exemption must be an exact repository path")
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ValueError("archive exemption requires an exact SHA-256")
    return entries


def verified_skip(root):
    entries = parse_manifest(read_regular(root, MANIFEST, MAX_MANIFEST_BYTES))
    for path, expected in entries.items():
        actual = hashlib.sha256(read_regular(root, path, MAX_SOURCE_BYTES)).hexdigest()
        if actual != expected:
            raise ValueError(f"archived source digest mismatch: {path}")
    return ",".join(f"./{path}" for path in sorted(entries))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[2]
    try:
        exclusions = verified_skip(root)
        if args.github_output is not None:
            with args.github_output.open("a", encoding="utf-8") as output:
                output.write(f"skip={exclusions}\n")
    except (OSError, UnicodeError, ValueError) as error:
        print(f"Codespell custody validation failed: {error}", file=sys.stderr)
        return 1
    print(
        f"Verified {len(exclusions.split(','))} exact archived paths for spelling only."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
