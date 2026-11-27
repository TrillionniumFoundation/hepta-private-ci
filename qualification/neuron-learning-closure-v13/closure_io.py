"""Descriptor-bound, nonblocking regular-file reads on POSIX hosts.

Unsupported hosts refuse this qualification profile instead of using a racy
check-then-open fallback. Ancestors above an explicitly supplied root belong to
the caller; every component below that opened root is traversed without links.
"""

from contextlib import contextmanager
import os
from pathlib import PurePosixPath
import stat


class ClosureError(ValueError):
    """A bounded content or identity check failed; no binding was produced."""


@contextmanager
def open_regular(path, maximum, *, root=None):
    if os.name != "posix" or not all(
        hasattr(os, name) for name in ("O_NOFOLLOW", "O_NONBLOCK")
    ):
        raise ClosureError("Descriptor-bound reads require the POSIX profile")
    if type(maximum) is not int or maximum < 1:
        raise ClosureError("Invalid file byte bound")
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    directory = descriptor = None
    try:
        if root is None:
            descriptor = os.open(path, flags)
        else:
            name = PurePosixPath(path)
            if (
                name.is_absolute()
                or not name.parts
                or ".." in name.parts
                or "\\" in str(path)
                or name.as_posix() != str(path)
            ):
                raise ClosureError("Invalid relative material path")
            directory = os.open(root, flags | os.O_DIRECTORY)
            for part in name.parts[:-1]:
                following = os.open(part, flags | os.O_DIRECTORY, dir_fd=directory)
                os.close(directory)
                directory = following
            descriptor = os.open(name.name, flags, dir_fd=directory)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
            raise ClosureError("Input is nonregular or exceeds its byte bound")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            yield stream
            after = os.fstat(stream.fileno())
            fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
            if any(getattr(before, name) != getattr(after, name) for name in fields):
                raise ClosureError("Input changed while its contents were read")
    except (OSError, NotImplementedError) as error:
        raise ClosureError("Cannot open a bounded, unlinked regular input") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if directory is not None:
            os.close(directory)


def read_capped(path, maximum):
    with open_regular(path, maximum) as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ClosureError("Input grew beyond its byte bound")
    return raw
