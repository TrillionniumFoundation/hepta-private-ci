"""Protected installation inputs and a bounded, non-authoritative install log."""

from contextlib import contextmanager
import hashlib
import json
import os
import re
from pathlib import Path
import stat


def unique_object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("duplicate JSON field")
        result[name] = value
    return result


def canonical(path):
    path = Path(path)
    if not path.is_absolute() or path != Path(os.path.normpath(path)):
        raise ValueError("path must be absolute and normalized")
    return path


def protected_parents(path, owner=0):
    for parent in reversed(canonical(path).parents):
        info = parent.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid not in {0, owner}
            or info.st_mode & 0o022
        ):
            raise ValueError("installation ancestor is not protected")


@contextmanager
def regular_file(path, owner=0):
    path = canonical(path)
    protected_parents(path, owner)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != owner
            or info.st_nlink != 1
            or info.st_mode & 0o022
        ):
            raise ValueError("installation input is not a protected regular file")
        yield fd, info
        current = path.lstat()
        after = os.fstat(fd)
        if (
            info.st_dev,
            info.st_ino,
            info.st_size,
            info.st_mtime_ns,
            info.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ) or (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
            raise ValueError("installation input changed during its read")
        protected_parents(path, owner)
    finally:
        os.close(fd)


def read_public(path, owner=0):
    with regular_file(path, owner) as (fd, info):
        if info.st_size > 65536:
            raise ValueError("public installation input exceeds 64 KiB")
        data = os.read(fd, 65537)
        if len(data) != info.st_size or len(data) > 65536:
            raise ValueError("public installation input exceeds 64 KiB")
        return data


def digest(data):
    return hashlib.sha256(data).hexdigest()


def program(pin):
    if set(pin) != {"path", "sha256"} or not re.fullmatch(
        "[0-9a-f]{64}", pin["sha256"]
    ):
        raise ValueError("invalid normal program pin")
    with regular_file(pin["path"]) as (fd, info):
        if not info.st_mode & 0o111 or info.st_size > 1024 * 1024 * 1024:
            raise ValueError("normal program is not executable or exceeds 1 GiB")
        hasher = hashlib.sha256()
        while chunk := os.read(fd, 1024 * 1024):
            hasher.update(chunk)
        if hasher.hexdigest() != pin["sha256"]:
            raise ValueError("normal program does not match its pin")
    return canonical(pin["path"])


def durable_create(path, data, mode=0o600, uid=0, gid=0):
    protected_parents(path, uid)
    fd = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, mode
    )
    try:
        os.fchown(fd, uid, gid)
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb", closefd=False) as out:
            out.write(data)
            out.flush()
            os.fsync(fd)
    finally:
        os.close(fd)
    barrier(path.parent)


def barrier(directory):
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def encode(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def log(namespace, phase, **fields):
    # A numbered, append-only external deployment observation, never a domain
    # journal or an authorization/retry instruction. No capability enters it.
    existing = list(namespace.glob("phase-*.json"))
    if len(existing) >= 32:
        raise ValueError("installation observation bound exceeded")
    durable_create(
        namespace / f"phase-{len(existing):02}.json", encode({"phase": phase, **fields})
    )


def renderer_bundle(request):
    pin = request["renderer_manifest"]
    raw = read_public(pin["path"])
    if digest(raw) != pin["sha256"]:
        raise ValueError("renderer bundle manifest differs")
    manifest = json.loads(raw, object_pairs_hook=unique_object)
    if (
        set(manifest) != {"schema", "makepad_revision", "files", "installs_services"}
        or manifest["schema"] != "hepta.native.renderer-bundle.v1"
        or manifest["installs_services"] is not False
    ):
        raise ValueError("invalid rendering-only bundle")
    directory = canonical(pin["path"]).parent
    entries = manifest["files"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= 256:
        raise ValueError("renderer bundle is not bounded")
    seen = set()
    for entry in entries:
        relative = Path(entry["path"])
        if (
            set(entry) != {"path", "sha256", "size"}
            or relative.is_absolute()
            or any(part in {"..", "."} for part in relative.parts)
            or str(relative) != entry["path"]
            or entry["path"] in seen
        ):
            raise ValueError("invalid or duplicate bundle path")
        seen.add(entry["path"])
        if not re.fullmatch("[0-9a-f]{64}", entry["sha256"]):
            raise ValueError("invalid resource digest")
        with regular_file(directory / relative) as (fd, info):
            if (
                info.st_size != entry["size"]
                or not 0 <= info.st_size <= 256 * 1024 * 1024
            ):
                raise ValueError("renderer resource size differs")
            hasher = hashlib.sha256()
            while chunk := os.read(fd, 1024 * 1024):
                hasher.update(chunk)
            if hasher.hexdigest() != entry["sha256"]:
                raise ValueError("renderer resource differs")
    if (
        "hepta-robrix" not in seen
        or not any(path.startswith("licenses/") for path in seen)
        or not any(path.startswith("resources/") for path in seen)
        or directory / "hepta-robrix" != canonical(request["renderer"]["path"])
    ):
        raise ValueError("renderer/resources/licenses are not the pinned bundle")
    return len(entries)
