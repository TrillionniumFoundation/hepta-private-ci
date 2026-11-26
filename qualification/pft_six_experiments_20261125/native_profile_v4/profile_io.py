"""Bounded, content-pinned research inputs. No model or authority imports."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat


class Refused(ValueError):
    pass


def require(value, message):
    if not value:
        raise Refused(message)


def digest(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)
            and value != "0" * 64, "nonzero SHA-256 required")
    return value


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def parse(raw, cap=1024 * 1024):
    require(0 < len(raw) <= cap, "JSON input size bound")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate JSON field")
            result[key] = value
        return result

    def nonfinite(_):
        raise Refused("nonfinite JSON number")

    return json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)


def fields(value, expected, label):
    require(isinstance(value, dict) and set(value) == set(expected), label + " fields")


def relative(value):
    require(isinstance(value, str) and 0 < len(value) <= 4096 and "\\" not in value,
            "portable relative path required")
    path = PurePosixPath(value)
    require(not path.is_absolute() and path.as_posix() == value
            and all(part not in (".", "..", "") for part in path.parts),
            "canonical relative path required")
    return path.parts


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def read_relative(root, name, cap):
    """Read a regular file through held no-follow directory descriptors."""
    parts = relative(name)
    current = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
            os.close(current)
            current = child
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=current)
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= cap,
                    "bounded regular file required")
            raw = stream.read(cap + 1)
            after = os.fstat(stream.fileno())
            require(_stamp(before) == _stamp(after) and len(raw) == before.st_size,
                    "input changed during capture")
            return raw
    finally:
        os.close(current)


def read_pin(root, pin, cap):
    fields(pin, ("path", "bytes", "sha256"), "artifact pin")
    digest(pin["sha256"])
    require(type(pin["bytes"]) is int and 0 < pin["bytes"] <= cap, "artifact byte bound")
    raw = read_relative(root, pin["path"], cap)
    require(len(raw) == pin["bytes"] and sha(raw) == pin["sha256"], "artifact pin differs")
    return raw


def read_named(path, expected, cap):
    """The operator supplies this path; data paths use read_pin instead."""
    path = Path(path)
    raw = read_relative(path.parent, path.name, cap)
    require(sha(raw) == digest(expected), "named input pin differs")
    return raw


def write_new(path, raw, cap):
    require(0 < len(raw) <= cap, "output size bound")
    path = Path(path)
    # Exclusive creation never replaces a candidate, state, or retained result.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    require(read_relative(path.parent, path.name, cap) == raw, "output readback differs")
    return {"path": path.name, "bytes": len(raw), "sha256": sha(raw)}
