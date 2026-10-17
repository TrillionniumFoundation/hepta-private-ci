"""Construct a clean private model runtime tree from independently verified bytes.

A source-byte receipt does not authorize runtime execution. It is only a frozen
allowlist, revalidated on input *and* on the resulting isolated copy. Local Hub
caches, symlinks, mutable siblings and unregistered source files are never copied.
No model imports, network, authority or model-loader calls belong in this module.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import stat
import tempfile

import preflight
import review_bytes

CHUNK = 4 * 1024 * 1024


def require(value, reason):
    if not value:
        raise review_bytes.Rejected(reason)


def _copy_exact(stage, runtime, item):
    name = item["filename"]
    require(preflight.member(name), "unsafe runtime filename")
    src = stage.joinpath(*name.split("/"))
    for parent in src.parents:
        if parent == stage:
            break
        require(parent.is_dir() and not parent.is_symlink(), "aliased source parent")
    require(src.is_file() and not src.is_symlink() and src.resolve().is_relative_to(stage.resolve()),
            "invalid runtime source path")
    dst = runtime.joinpath(*name.split("/"))
    dst.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    source_fd = os.open(src, flags)
    try:
        initial = os.fstat(source_fd)
        count = item["published_size"]
        require(stat.S_ISREG(initial.st_mode) and initial.st_size == count and
                0 < count <= preflight.MAX_WEIGHT_BYTES, "source size/type drift")
        target_fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                            getattr(os, "O_NOFOLLOW", 0), 0o600)
        h = hashlib.sha256()
        blob = hashlib.sha1(b"blob " + str(count).encode() + b"\0")
        length = 0
        try:
            with os.fdopen(target_fd, "wb") as target:
                while block := os.read(source_fd, min(CHUNK, count - length + 1)):
                    length += len(block)
                    require(length <= count, "changed or oversized input during isolated copy")
                    h.update(block)
                    blob.update(block)
                    target.write(block)
                target.flush()
                os.fsync(target.fileno())
        except BaseException:
            raise
        final = os.fstat(source_fd)
        require(length == count and
                (initial.st_dev, initial.st_ino, initial.st_size, initial.st_mtime_ns) ==
                (final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns),
                "runtime source mutated during copy")
        expected = h.hexdigest() if item["source_identity_type"] == "lfs_sha256" else blob.hexdigest()
        require(expected == item["source_identity"], "runtime copied bytes differ from pinned source")
    finally:
        os.close(source_fd)


@contextmanager
def isolated_verified_runtime(source_receipt, stage):
    """Yield a temporary allowlist-only filesystem tree, guaranteed removed on exit.

    This is not a namespace/process sandbox; the immutable-source boundary is
    defended only against ordinary filesystem drift. No original issuer signing.
    """
    stage = Path(stage)
    require(stage.is_dir() and not stage.is_symlink(), "invalid source stage")
    review_bytes.audit(source_receipt, stage)
    inventory = source_receipt["selected_source_inventory"]
    require(type(inventory) is list and 0 < len(inventory) <= preflight.MAX_FILES,
            "invalid runtime manifest")
    with tempfile.TemporaryDirectory(prefix="hepta-verified-runtime-") as directory:
        runtime = Path(directory)
        for item in inventory:
            require(type(item) is dict and set(item) == {
                "filename", "published_size", "source_identity_type", "source_identity", "is_weight"},
                "unexpected runtime inventory object")
            _copy_exact(stage, runtime, item)
        result = review_bytes.audit(source_receipt, runtime)
        require(result["independently_rehashed_exact_physical_bytes"] is True and
                result["file_count"] == len(inventory), "isolated runtime failed independent review")
        yield runtime
