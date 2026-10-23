"""Flush retained directory entries where the platform exposes that operation.

Directory fsync is unavailable through this API on Windows. Successful flushes
describe requested OS operations, not a completed power-loss recovery experiment.
"""

import os
from pathlib import Path


DIRECTORY_FSYNC_SUPPORTED = os.name != "nt"


def capabilities():
    return {
        "directory_fsync": DIRECTORY_FSYNC_SUPPORTED,
        "directory_policy": "posix_fsync"
        if DIRECTORY_FSYNC_SUPPORTED
        else "unsupported_on_windows",
        "sqlite_synchronous": "FULL",
        "power_loss_recovery_verified": False,
    }


def sync_directory(path):
    """Flush one directory or explicitly report the unsupported platform case."""
    if not DIRECTORY_FSYNC_SUPPORTED:
        return False
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return True


def create_directory(path, *, parents=False, exist_ok=False):
    """Persist every newly created parent/child link before publishing its use."""
    path = Path(path)
    missing, current = [], path
    while not current.exists():
        if current.is_symlink():
            raise ValueError("directory chain contains a dangling symlink")
        missing.append(current)
        current = current.parent
    path.mkdir(parents=parents, exist_ok=exist_ok)
    for created in reversed(missing or [path]):
        sync_directory(created.parent)
        sync_directory(created)
    return path
