"""Bounded checkpoint reads shared by metadata inspection and tensor admission.

This checks file bytes, not trusted roots or production authorization. Callers
retain their existing path and independent expected-digest contracts.
"""

import os
from pathlib import Path
import stat

MAX_MANIFEST_BYTES = 256 * 1024
MAX_ADAPTER_BYTES = 64 * 1024 * 1024


def bounded_read(path: Path, limit: int) -> bytes:
    """Admit only bounded regular files; reject nonregular paths before reading.

    POSIX no-follow/nonblocking flags close replacement races at open. Other
    platforms retain pre/post-open identity checks, without an atomic no-follow
    guarantee when their os module does not expose that flag.
    """
    if type(limit) is not int or limit <= 0:
        raise ValueError("positive candidate byte bound required")
    before_open = path.lstat()
    if stat.S_ISLNK(before_open.st_mode):
        raise ValueError("candidate symlink is not an admitted immutable file")
    if not stat.S_ISREG(before_open.st_mode):
        raise ValueError("candidate must be a regular file")
    if not 0 < before_open.st_size <= limit:
        raise ValueError("candidate byte bound")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or not os.path.samestat(
            before_open, opened
        ):
            raise ValueError("candidate file identity changed during open")
        if not 0 < opened.st_size <= limit:
            raise ValueError("candidate byte bound")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            payload = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
        if (
            len(payload) != opened.st_size
            or not 0 < len(payload) <= limit
            or any(
                getattr(opened, field) != getattr(after, field)
                for field in ("st_size", "st_mtime_ns", "st_ctime_ns")
            )
        ):
            raise ValueError("candidate file changed during bounded read")
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return payload
