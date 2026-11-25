"""Snapshot declared runtime paths and bind actual installed distribution files.

This is a byte inventory, not a complete import/native-loader closure, authority,
or a guarantee against modification after verification. No dependency code is
imported. Use immutable owner-controlled materials for execution.
"""

import argparse
import hashlib
import importlib.metadata
import os
from pathlib import Path, PurePosixPath
import re
import stat

from . import data

SCHEMA = "hepta.paired-learning.runtime-artifacts.v1"
MAX_FILES = 65536
MAX_BYTES = 16 * 1024**3
MAX_MANIFEST_BYTES = 32 * 1024**2
SAFE_DIRECTORY_IO = (
    hasattr(os, "O_NOFOLLOW")
    and hasattr(os, "O_DIRECTORY")
    and os.open in os.supports_dir_fd
    and os.stat in os.supports_dir_fd
    and os.stat in os.supports_follow_symlinks
    and os.scandir in os.supports_fd
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def relative(value):
    require(
        isinstance(value, str)
        and 0 < len(value.encode("utf-8")) <= 4096
        and "\\" not in value
        and ":" not in value
        and not any(ord(c) < 32 for c in value)
        and not value.startswith("/")
        and all(part not in ("", ".", "..") for part in value.split("/")),
        "invalid portable runtime artifact path",
    )
    return value


def _roots(roots):
    require(
        isinstance(roots, list) and 0 < len(roots) <= 256,
        "bounded runtime roots required",
    )
    for root in roots:
        relative(root)
    require(roots == sorted(set(roots)), "runtime roots must be sorted and unique")
    require(
        not any(
            b.startswith(a + "/") for i, a in enumerate(roots) for b in roots[i + 1 :]
        ),
        "overlapping runtime roots",
    )


def validate(manifest):
    """Validate the portable wire object without claiming local material access."""
    require(
        isinstance(manifest, dict)
        and set(manifest)
        == {"schema", "roots", "files", "inventory_sha256", "total_bytes"}
        and manifest["schema"] == SCHEMA,
        "invalid runtime artifact manifest",
    )
    roots, files = manifest["roots"], manifest["files"]
    _roots(roots)
    require(
        isinstance(files, list) and 0 < len(files) <= MAX_FILES,
        "bounded runtime files required",
    )
    paths, total = [], 0
    covered = set()
    for entry in files:
        require(
            isinstance(entry, dict) and set(entry) == {"path", "sha256", "size"},
            "invalid runtime artifact entry",
        )
        path = relative(entry["path"])
        owners = [root for root in roots if path == root or path.startswith(root + "/")]
        require(len(owners) == 1, "runtime file outside declared roots")
        covered.update(owners)
        require(
            type(entry["size"]) is int and 0 <= entry["size"] <= MAX_BYTES,
            "invalid runtime artifact size",
        )
        require(
            isinstance(entry["sha256"], str)
            and re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]),
            "invalid runtime artifact digest",
        )
        paths.append(path)
        total += entry["size"]
    require(paths == sorted(set(paths)), "runtime files must be sorted and unique")
    require(covered == set(roots), "empty runtime root")
    require(
        type(manifest["total_bytes"]) is int
        and total == manifest["total_bytes"] <= MAX_BYTES,
        "runtime byte budget differs",
    )
    require(
        manifest["inventory_sha256"] == data.digest(files),
        "runtime inventory digest differs",
    )
    require(
        len(data.canonical(manifest)) <= MAX_MANIFEST_BYTES,
        "runtime manifest exceeds byte limit",
    )
    return manifest


def _identity(info):
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def snapshot(root, roots):
    """Hash exact declared paths through descriptor-relative, no-follow opens."""
    _roots(roots)
    require(
        SAFE_DIRECTORY_IO,
        "runtime artifact verification requires safe descriptor-relative filesystem operations",
    )
    supplied = Path(root)
    require(not supplied.is_symlink(), "symlinked runtime material root")
    base = supplied.resolve(strict=True)
    require(base.is_dir(), "runtime material root must be a directory")
    files, directories = [], {}
    total = visited = 0
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    file_flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0)

    def directory(logical, info):
        require(
            stat.S_ISDIR(info.st_mode), "symlinked or non-directory runtime artifact"
        )
        original = directories.setdefault(logical, _identity(info))
        require(original == _identity(info), "runtime directory changed")

    def open_directory(parent, name, logical):
        before = os.stat(name, dir_fd=parent, follow_symlinks=False)
        directory(logical, before)
        descriptor = os.open(name, directory_flags, dir_fd=parent)
        try:
            require(
                _identity(os.fstat(descriptor)) == _identity(before),
                "runtime directory changed before open",
            )
        except BaseException:
            os.close(descriptor)
            raise
        return descriptor

    def visit(parent, name, logical):
        nonlocal total, visited
        relative(logical)
        require(
            len(PurePosixPath(logical).parts) <= 128, "runtime directory depth exceeded"
        )
        visited += 1
        require(visited <= MAX_FILES * 2, "runtime entry budget exceeded")
        before = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if stat.S_ISDIR(before.st_mode):
            descriptor = open_directory(parent, name, logical)
            try:
                with os.scandir(descriptor) as entries:
                    for entry in entries:
                        visit(descriptor, entry.name, logical + "/" + entry.name)
                require(
                    _identity(os.fstat(descriptor)) == _identity(before),
                    "runtime directory changed during hashing",
                )
                require(
                    _identity(os.stat(name, dir_fd=parent, follow_symlinks=False))
                    == _identity(before),
                    "runtime directory path changed during hashing",
                )
            finally:
                os.close(descriptor)
            return
        require(
            stat.S_ISREG(before.st_mode), "symlinked or nonregular runtime artifact"
        )
        require(
            len(files) < MAX_FILES and total + before.st_size <= MAX_BYTES,
            "runtime artifact budget exceeded",
        )
        with os.fdopen(os.open(name, file_flags, dir_fd=parent), "rb") as stream:
            require(
                _identity(os.fstat(stream.fileno())) == _identity(before),
                "runtime artifact changed before hashing",
            )
            digest, count = hashlib.sha256(), 0
            while block := stream.read(1024**2):
                count += len(block)
                require(count <= before.st_size, "runtime artifact grew during hashing")
                digest.update(block)
            require(
                count == before.st_size
                and _identity(os.fstat(stream.fileno())) == _identity(before),
                "runtime artifact changed during hashing",
            )
        require(
            _identity(os.stat(name, dir_fd=parent, follow_symlinks=False))
            == _identity(before),
            "runtime artifact path changed during hashing",
        )
        files.append(dict(path=logical, size=count, sha256=digest.hexdigest()))
        total += count

    def open_chain(base_descriptor, parts):
        require(len(parts) <= 128, "runtime directory depth exceeded")
        descriptor = os.dup(base_descriptor)
        logical = []
        try:
            for component in parts:
                logical.append(component)
                child = open_directory(descriptor, component, "/".join(logical))
                os.close(descriptor)
                descriptor = child
        except BaseException:
            os.close(descriptor)
            raise
        return descriptor

    before = base.lstat()
    directory("", before)
    base_descriptor = os.open(base, directory_flags)
    try:
        require(
            _identity(os.fstat(base_descriptor)) == _identity(before),
            "runtime material root changed before open",
        )
        for selected in roots:
            parts = PurePosixPath(selected).parts
            descriptor = open_chain(base_descriptor, parts[:-1])
            try:
                visit(descriptor, parts[-1], selected)
            finally:
                os.close(descriptor)
        for logical, expected in directories.items():
            descriptor = open_chain(base_descriptor, PurePosixPath(logical).parts)
            try:
                require(
                    _identity(os.fstat(descriptor)) == expected,
                    "runtime directory changed during hashing",
                )
            finally:
                os.close(descriptor)
        require(
            _identity(base.lstat()) == _identity(before),
            "runtime material root path changed during hashing",
        )
    finally:
        os.close(base_descriptor)
    files.sort(key=lambda item: item["path"])
    return validate(
        dict(
            schema=SCHEMA,
            roots=list(roots),
            files=files,
            inventory_sha256=data.digest(files),
            total_bytes=total,
        )
    )


def verify_installed(manifest, root, package_names):
    """Rehash materials and require the actual selected distributions inside them.

    RECORD coverage is necessary but does not enumerate transitive dependencies,
    arbitrary import hooks, native shared libraries or operating-system state.
    """
    validate(manifest)
    require(
        snapshot(root, manifest["roots"]) == manifest,
        "runtime artifact bytes or inventory differ",
    )
    base = Path(root).resolve(strict=True)
    expected = {entry["path"] for entry in manifest["files"]}
    for name in package_names:
        distribution = importlib.metadata.distribution(name)
        require(
            distribution.files is not None and distribution.files,
            "installed dependency has no file inventory",
        )
        require(
            len(distribution.files) <= MAX_FILES,
            "installed dependency inventory exceeds budget",
        )
        for entry in distribution.files:
            path = Path(distribution.locate_file(entry))
            require(not path.is_symlink(), "symlinked installed dependency artifact")
            try:
                logical = path.resolve(strict=True).relative_to(base).as_posix()
            except ValueError as exc:
                raise ValueError(
                    "installed dependency outside runtime material root"
                ) from exc
            require(
                logical in expected,
                "installed dependency absent from runtime inventory",
            )
    return manifest


def load(path, expected_sha256):
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_MANIFEST_BYTES + 1)
    require(len(raw) <= MAX_MANIFEST_BYTES, "runtime manifest exceeds byte limit")
    manifest = validate(data._parse(raw))
    require(
        data.digest(manifest) == expected_sha256, "runtime manifest commitment differs"
    )
    return manifest


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("roots", nargs="+")
    args = parser.parse_args()
    result = snapshot(args.root, sorted(args.roots))
    with args.output.open("xb") as stream:
        stream.write(data.canonical(result) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    print(data.digest(result))


if __name__ == "__main__":
    main()
