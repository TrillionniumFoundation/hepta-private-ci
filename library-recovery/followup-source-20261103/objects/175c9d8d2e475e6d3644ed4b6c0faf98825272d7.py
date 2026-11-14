#!/usr/bin/env python3
"""Read-only byte provenance for the 16-run CellSplit host matrix.

These hashes let an independent observer compare retained raw files with
reported measurements. They are *not* owner signatures, proof of physical
execution, or production authorization. Fail closed on preexisting result
paths, symlinks, hardlinks, nonregular files and concurrently edited files.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any

MAX_MEASUREMENT_BYTES = 8 * 1024 * 1024
MAX_LOG_BYTES = 128 * 1024 * 1024
READ_CHUNK_BYTES = 1024 * 1024


class CaptureIntegrityError(ValueError):
    """A per-run measurement does not have fresh, reproducible provenance."""


def require_absent(path: Path) -> None:
    """lstat catches dangling symlinks, which Path.exists would miss."""
    try:
        os.lstat(path)
    except FileNotFoundError:
        return
    raise CaptureIntegrityError(f"preexisting measurement path: {path}")


def _open_regular_once(path: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    # On systems without O_NOFOLLOW, lstat is still a fail-closed preflight;
    # fstat below prevents directories and devices from entering the capture.
    before_path = os.lstat(path)
    if stat.S_ISLNK(before_path.st_mode):
        raise CaptureIntegrityError(f"symlink not accepted: {path}")
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise CaptureIntegrityError(f"cannot open regular evidence file {path}: {exc}") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise CaptureIntegrityError(f"regular single-link file required: {path}")
        # A pathname swap between lstat and open must not rebind the result.
        current_path = os.lstat(path)
        if (before_path.st_dev, before_path.st_ino) != (info.st_dev, info.st_ino) or (
            current_path.st_dev, current_path.st_ino
        ) != (info.st_dev, info.st_ino):
            raise CaptureIntegrityError(f"evidence pathname changed: {path}")
    except BaseException:
        os.close(fd)
        raise
    return fd


def _snapshot(path: Path, limit: int, collect_bytes: bool) -> tuple[bytes, str]:
    try:
        fd = _open_regular_once(path)
    except OSError as exc:
        raise CaptureIntegrityError(f"evidence path missing: {path}: {exc}") from exc
    try:
        before = os.fstat(fd)
        if before.st_size > limit:
            raise CaptureIntegrityError(f"evidence file exceeds size limit: {path}")
        digest = hashlib.sha256()
        parts: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, min(READ_CHUNK_BYTES, limit - total + 1))
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise CaptureIntegrityError(f"evidence file grew beyond limit: {path}")
            digest.update(chunk)
            if collect_bytes:
                parts.append(chunk)
        after = os.fstat(fd)
        identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
        if total != before.st_size or identity_before != identity_after:
            raise CaptureIntegrityError(f"evidence file changed during capture: {path}")
        current_path = os.lstat(path)
        if (current_path.st_dev, current_path.st_ino) != (
            before.st_dev,
            before.st_ino,
        ):
            raise CaptureIntegrityError(f"evidence path replaced during capture: {path}")
        return (b"".join(parts) if collect_bytes else b"", digest.hexdigest())
    finally:
        os.close(fd)


def capture_run_files(
    result_path: Path, stdout_path: Path, stderr_path: Path, argv: list[str]
) -> tuple[bytes, dict[str, Any]]:
    """Hash exactly the raw bytes used for validation; never infer counters."""
    if not argv or not all(isinstance(arg, str) and arg for arg in argv):
        raise CaptureIntegrityError("invalid command for provenance")
    raw, raw_digest = _snapshot(result_path, MAX_MEASUREMENT_BYTES, True)
    _, stdout_digest = _snapshot(stdout_path, MAX_LOG_BYTES, False)
    _, stderr_digest = _snapshot(stderr_path, MAX_LOG_BYTES, False)
    command = json.dumps(argv, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return raw, {
        "raw_measurement_sha256": raw_digest,
        "stdout_sha256": stdout_digest,
        "stderr_sha256": stderr_digest,
        "argv_sha256": hashlib.sha256(command).hexdigest(),
    }


def write_new_durable(path: Path, data: bytes) -> None:
    """Create-only diagnostic evidence: a crashed publish never overwrites history."""
    try:
        with path.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if os.name == "posix":
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            directory_fd = os.open(path.parent, flags)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except FileExistsError as exc:
        raise CaptureIntegrityError(f"evidence already published: {path}") from exc
