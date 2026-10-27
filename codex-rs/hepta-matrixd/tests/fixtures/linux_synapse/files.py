"""Bounded file identities and durable non-overwriting evidence publication."""

import ctypes
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile


SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def checksum(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def relative(name):
    if not isinstance(name, str) or not name or "\\" in name or ":" in name:
        raise ValueError("Invalid relative evidence path")
    path = PurePosixPath(name)
    if (
        not path.parts
        or path.is_absolute()
        or ".." in path.parts
        or path.as_posix() != name
    ):
        raise ValueError("Noncanonical relative evidence path")
    if any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise ValueError("Control character in evidence path")
    return name


def physical(path):
    """Validate every existing ancestor before any creation or publication."""
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts or path.as_posix() != str(path):
        raise ValueError("Expected an absolute canonical path")
    for item in reversed((path, *path.parents)):
        if item.is_symlink():
            raise ValueError(f"Symlink in evidence authority: {path}")
        if item.exists() and item != path and not item.is_dir():
            raise ValueError(f"Non-directory ancestor in evidence authority: {path}")
    return path


def regular(path):
    path = physical(path)
    metadata = path.stat()
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"Expected a regular file: {path}")
    return path


def describe(path):
    path = regular(path)
    return {"bytes": path.stat().st_size, "sha256": checksum(path)}


def verify(path, expected):
    if (
        not isinstance(expected, dict)
        or set(expected) != {"bytes", "sha256"}
        or type(expected["bytes"]) is not int
    ):
        raise ValueError("Malformed file identity")
    if (
        expected["bytes"] < 0
        or not isinstance(expected["sha256"], str)
        or not SHA256.fullmatch(expected["sha256"])
    ):
        raise ValueError("Malformed file size or SHA-256")
    if describe(path) != expected:
        raise ValueError(f"File identity differs: {path}")


def inventory(directory):
    directory = physical(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("Expected a physical evidence directory")
    result = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Symlink in evidence tree: {path}")
        if path.is_file():
            result[path.relative_to(directory).as_posix()] = describe(path)
        elif not path.is_dir():
            raise ValueError(f"Special entry in evidence tree: {path}")
    return result


def read_json(path, expected_sha=None):
    path = regular(path)
    if expected_sha is not None:
        if not SHA256.fullmatch(expected_sha) or checksum(path) != expected_sha:
            raise ValueError("JSON authority SHA differs from the frozen input")

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(path.read_text(), object_pairs_hook=unique_object)


def fsync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_bytes(path, data, *, mode=0o600):
    path = physical(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.parent.resolve(strict=True) != path.parent:
        raise ValueError("Evidence parent contains a symlink")
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode
    )
    with os.fdopen(descriptor, "wb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    fsync_directory(path.parent)


def write_json(path, value):
    write_bytes(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode())


def copy_file(source, destination, *, executable=False):
    source = regular(source)
    before = describe(source)
    destination = physical(destination)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with source.open("rb") as original, destination.open("xb") as output:
        shutil.copyfileobj(original, output, 1024 * 1024)
        os.fchmod(output.fileno(), 0o500 if executable else 0o600)
        output.flush()
        os.fsync(output.fileno())
    fsync_directory(destination.parent)
    verify(destination, before)
    verify(source, before)
    return before


def atomic_publish(directory, destination):
    """Linux renameat2 NOREPLACE; unsupported kernels fail rather than overwrite."""
    directory, destination = physical(directory), physical(destination)
    if directory.parent != destination.parent or directory.is_symlink():
        raise ValueError("Atomic publication requires physical sibling directories")
    if not directory.is_dir() or destination.exists() or destination.is_symlink():
        raise ValueError("Publication destination already exists or source is absent")
    fsync_directory(directory)
    library = ctypes.CDLL(None, use_errno=True)
    rename = library.renameat2
    rename.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(directory), -100, os.fsencode(destination), 1) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(destination))
    fsync_directory(destination.parent)


def stage_directory(parent, name):
    parent = physical(parent)
    if parent.is_symlink() or not parent.is_dir():
        raise ValueError("Evidence parent must already be a physical directory")
    relative(name)
    if "/" in name:
        raise ValueError("Publication name must be one path component")
    return Path(tempfile.mkdtemp(prefix=f".{name}.staging.", dir=parent))
