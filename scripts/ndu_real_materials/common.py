"""Small immutable byte bindings shared by registration and trusted evaluation."""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def binding(path, root):
    path = Path(path)
    data = path.read_bytes()
    return {"path": path.relative_to(root).as_posix(), "sha256": digest(data), "bytes": len(data)}


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(json_bytes(value))


def read_relative(root, relative, limit=32 * 1024 * 1024):
    if not isinstance(relative, str):
        raise ValueError("Artifact path must be text")
    path = PurePosixPath(relative)
    if ("\\" in relative or path.is_absolute()
            or str(path) != relative or any(part in {".", ".."} for part in path.parts)):
        raise ValueError("Noncanonical or escaping artifact path")
    if not path.parts:
        raise ValueError("Empty artifact path")
    fd = os.open(Path(root).resolve(strict=True), os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        data_fd = os.open(path.parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    finally:
        os.close(fd)
    with os.fdopen(data_fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise ValueError("Artifact is not a bounded regular file")
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    if ((before.st_size, before.st_mtime_ns, before.st_ctime_ns) !=
            (after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
        raise ValueError("Artifact changed while being read")
    if len(raw) > limit:
        raise ValueError("Artifact grew past its byte bound")
    return raw


def read_bound(root, value, limit=32 * 1024 * 1024):
    if set(value) != {"path", "sha256", "bytes"}:
        raise ValueError("Closed byte binding required")
    if type(value["bytes"]) is not int or not 0 <= value["bytes"] <= limit:
        raise ValueError("Invalid artifact byte bound")
    raw = read_relative(root, value["path"], limit)
    if len(raw) != value["bytes"] or digest(raw) != value["sha256"]:
        raise ValueError("Artifact differs from the registered bytes")
    return raw


def strict_json(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError("Duplicate JSON key")
            value[key] = item
        return value
    def reject(value):
        raise ValueError("Nonfinite JSON number")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=reject)
