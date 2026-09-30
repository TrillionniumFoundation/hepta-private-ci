#!/usr/bin/env python3
"""Target-host namespace durability probe for learning.artifacts.

This establishes process-visible fsync/rename/no-follow behavior on the selected
filesystem. It explicitly does NOT claim physical power-loss survival.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import tempfile
from pathlib import Path


def fsync_dir(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--source-tree", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    if len(args.source_sha) != 40 or len(args.source_tree) != 40:
        raise SystemExit("source identity must use full SHA-1 object ids")
    root = args.root.resolve(strict=True)
    if not root.is_dir():
        raise SystemExit("target root must be a directory")

    with tempfile.TemporaryDirectory(prefix=".hepta-artifact-fs-", dir=root) as temporary:
        work = Path(temporary)
        initial = work / "initial"
        renamed = work / "renamed"
        payload = b"hepta-learning-artifacts-target-fs-v1\n"

        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(initial, flags, 0o600)
        try:
            os.write(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        fsync_dir(work)

        os.replace(initial, renamed)
        fsync_dir(work)
        descriptor = os.open(renamed, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            observed = os.read(descriptor, len(payload) + 1)
        finally:
            os.close(descriptor)
        if observed != payload:
            raise SystemExit("renamed durable payload mismatch")

        symlink_nofollow = None
        if hasattr(os, "symlink") and hasattr(os, "O_NOFOLLOW"):
            link = work / "link"
            os.symlink(renamed.name, link)
            try:
                os.open(link, os.O_RDONLY | os.O_NOFOLLOW)
            except OSError:
                symlink_nofollow = True
            else:
                symlink_nofollow = False
            if not symlink_nofollow:
                raise SystemExit("O_NOFOLLOW unexpectedly opened a symlink")

        os.unlink(renamed)
        fsync_dir(work)
        receipt = {
            "schema": "hepta.learning-artifacts.target-fs-qualification.v1",
            "candidateSha": args.source_sha,
            "candidateTree": args.source_tree,
            "platform": platform.platform(),
            "machine": platform.machine(),
            "filesystemDevice": os.stat(root).st_dev,
            "directoryFsync": True,
            "atomicRenameObserved": True,
            "nofollowSymlinkRejected": symlink_nofollow,
            "physicalPowerLossProven": False,
            "payloadDigest": hashlib.sha256(payload).hexdigest(),
        }

    encoded = (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
