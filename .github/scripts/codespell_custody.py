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

# These retained qualification inputs admit only their registered original bytes.
QUALIFICATION_SOURCE_SHA256 = {
    (
        "qualification/hcsn_differentiable/evidence/p0p5-20261110/review/"
        "baseline36-c1-native-v1/v2/bootstrap/"
        "6e1c204a063b39f1fff14c405c09d153fe3ca57f.json"
    ): "1511fe97bec17637deef2dd336b97f8bb04dbc6421708d55909896e9f6bba6e6",
    (
        "qualification/hcsn_differentiable/evidence/"
        "p0p5-ci-launch-closure-20261110/codespell-fix/original-red.stdout"
    ): "bb3963bb62ee320e71703f057b98c1e71ceae250421f0b076e838ed7704ddd13",
    (
        "qualification/hcsn_differentiable/evidence/"
        "p0p5-persistence-validation-20261111/native-first/COMMAND.sh"
    ): "21487e097fbdef884fe979b8a2fcdfc59ebeed79fcc42fefea21f45e10135607",
    (
        "qualification/hcsn_differentiable/evidence/"
        "p0p5-persistence-validation-20261111/native-first/LAUNCH-RECEIPT.json"
    ): "a8e1c389662c60f512127826f927aba894793721276f62445ffa8746c58cac32",
    (
        "qualification/hcsn_differentiable/evidence/"
        "p0p5-terminal-numerics-20261110/numerical-audit/collector-launch/"
        "git-response.json"
    ): "7aa48d5cc91d125540591b852b64ec4255e8a4002b5c890d18d515bb9a6c4121",
    "qualification/hcsn_initial_vjp/evidence/native001/COMMAND.sh": "79d8d7bec29c774aeb094eb2ccceb02a5d6b44ebc1a239b33f26500758260945",
    (
        "qualification/hcsn_joint_dde/evidence/all-visits-attempt002/"
        "review_visited_l8_raw.py"
    ): "d2397d0b3e2dfaea8f32e7ec12a580650131dc428ac4d6a117110045489d1450",
}


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
            or not (
                re.fullmatch(r"library-recovery/[A-Za-z0-9._/-]+", path)
                or path in QUALIFICATION_SOURCE_SHA256
            )
            or str(PurePosixPath(path)) != path
            or any(part in {".", ".."} for part in path.split("/"))
            or len(PurePosixPath(path).parts) < 3
        ):
            raise ValueError("archive exemption must be an exact repository path")
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ValueError("archive exemption requires an exact SHA-256")
        if (
            path in QUALIFICATION_SOURCE_SHA256
            and expected != QUALIFICATION_SOURCE_SHA256[path]
        ):
            raise ValueError("qualification exemption requires its registered SHA-256")
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
