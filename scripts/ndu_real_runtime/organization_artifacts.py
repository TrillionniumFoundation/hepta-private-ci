"""Bounded original-artifact reads for the reference organization reviewer."""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat

from .causal_protocol import digest


def _version(info):
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON field")
            result[key] = value
        return result

    def constant(value):
        raise ValueError("non-finite JSON constant: " + value)

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


class _Reader:
    def __init__(self, root):
        self.root = Path(root).resolve(strict=True)
        self.bytes = 0
        self.reads = 0

    def read(self, ref):
        name = ref["path"]
        if not isinstance(name, str) or len(name) > 1024:
            raise ValueError("invalid artifact path")
        relative = PurePosixPath(name)
        if (
            relative.is_absolute()
            or "\\" in name
            or any(p in {"", ".", ".."} for p in name.split("/"))
        ):
            raise ValueError("unsafe artifact path")
        if (
            type(ref["bytes"]) is not int
            or not 0 < ref["bytes"] <= 8 * 1024**2
            or not digest(ref["sha256"])
        ):
            raise ValueError("invalid artifact size or digest")
        self.bytes += ref["bytes"]
        self.reads += 1
        if self.bytes > 64 * 1024**2 or self.reads > 4096:
            raise ValueError("review artifact budget exceeded")
        # Traverse from a held directory descriptor. A concurrent parent-link
        # swap must not redirect a read outside the evidence root.
        directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in relative.parts[:-1]:
                following = os.open(
                    part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
                )
                os.close(directory)
                directory = following
            descriptor = os.open(
                relative.name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=directory,
            )
            with os.fdopen(descriptor, "rb") as stream:
                before = os.fstat(stream.fileno())
                if not stat.S_ISREG(before.st_mode) or before.st_size != ref["bytes"]:
                    raise ValueError("artifact is absent or changed")
                raw = stream.read(ref["bytes"] + 1)
                after = os.fstat(stream.fileno())
            current = os.stat(relative.name, dir_fd=directory, follow_symlinks=False)
        finally:
            os.close(directory)
        if (
            _version(before) != _version(after)
            or _version(after) != _version(current)
            or len(raw) != ref["bytes"]
            or hashlib.sha256(raw).hexdigest() != ref["sha256"]
        ):
            raise ValueError("artifact bytes changed")
        return _strict_json(raw)
