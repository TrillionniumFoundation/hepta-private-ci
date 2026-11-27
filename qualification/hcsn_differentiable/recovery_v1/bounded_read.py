"""Read one bounded regular-file snapshot through a single retained descriptor."""

import os
from pathlib import Path
import stat


def _identity(metadata):
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def read_regular_bytes(path, limit, *, nonempty=False):
    if type(limit) is not int or limit < 1:
        raise ValueError("file byte limit must be a positive integer")
    path = Path(path)
    before = path.lstat()
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_size > limit
        or (nonempty and before.st_size == 0)
    ):
        raise ValueError("not a bounded regular file")
    flags = os.O_RDONLY
    for name in ("O_NONBLOCK", "O_NOFOLLOW", "O_CLOEXEC", "O_BINARY"):
        flags |= getattr(os, name, 0)
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or _identity(opened) != _identity(before):
            raise ValueError("file changed before read")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(limit + 1)
        after = os.fstat(fd)
        current = path.lstat()
        if (
            len(raw) > limit
            or len(raw) != before.st_size
            or _identity(after) != _identity(before)
            or not stat.S_ISREG(current.st_mode)
            or _identity(current) != _identity(before)
        ):
            raise ValueError("file changed during read or exceeded bound")
        return raw
    finally:
        os.close(fd)
