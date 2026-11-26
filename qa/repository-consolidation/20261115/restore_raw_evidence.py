"""Restore exact historical evidence from individually compressed containers."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import zlib


INDEX_SHA256 = {
    "qa/repository-consolidation/20261126/direct-vendor-exact/raw-evidence-storage.json": "25f9d9b675c9227c2c90897dac90b707529979b55617b4a4932eb9a69b2463d9",
}
MAX_BYTES = 8 * 1024 * 1024


def relative_path(name):
    if not isinstance(name, str) or "\\" in name or ":" in name or "\0" in name:
        raise ValueError("evidence path must use repository-relative syntax")
    path = Path(name)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("evidence path must remain relative to the repository")
    if path.as_posix() != name or not path.parts:
        raise ValueError("evidence path must be canonical")
    return path


def identity(value):
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
        value.st_mode,
        value.st_nlink,
    )


def read_regular(repo, relative, limit):
    path = repo / relative_path(relative)
    if not 0 <= limit <= MAX_BYTES:
        raise ValueError("invalid evidence byte bound")
    if any(parent.is_symlink() for parent in path.parents):
        raise ValueError("evidence parent must not be a symbolic link")
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise ValueError("evidence must be a regular single-link file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    flags |= getattr(os, "O_BINARY", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        opened = os.fstat(stream.fileno())
        if identity(opened) != identity(before):
            raise ValueError("evidence changed before reading")
        data = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    if (
        identity(after) != identity(before)
        or identity(path.lstat()) != identity(before)
        or len(data) > limit
    ):
        raise ValueError("evidence changed during reading or exceeds its bound")
    return data


def entries(repo):
    result = {}
    for index, expected in INDEX_SHA256.items():
        raw = read_regular(repo, index, 1024 * 1024)
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("registered evidence storage inventory changed")
        document = json.loads(raw)
        if document["schema"] != "hepta.raw-evidence.storage.v1":
            raise ValueError("unsupported raw evidence storage schema")
        for entry in document["files"]:
            name = relative_path(entry["original_path"]).as_posix()
            if name in result or entry["stored_path"] != name + ".evidence.gz":
                raise ValueError("duplicate or inconsistent stored evidence path")
            result[name] = entry
    return result


def read_verified(repo, relative, expected_bytes, expected_sha256):
    if type(expected_bytes) is not int or not 0 <= expected_bytes <= MAX_BYTES:
        raise ValueError("invalid original evidence byte bound")
    if not isinstance(expected_sha256, str) or not re.fullmatch(
        r"[0-9a-f]{64}", expected_sha256
    ):
        raise ValueError("invalid original evidence checksum")
    relative = relative_path(str(relative)).as_posix()
    path = repo / relative
    if path.exists() or path.is_symlink():
        data = read_regular(repo, relative, expected_bytes)
    else:
        entry = entries(repo)[relative]
        if (
            entry["original_bytes"] != expected_bytes
            or entry["original_sha256"] != expected_sha256
        ):
            raise ValueError("storage index differs from the original manifest")
        compressed = read_regular(repo, entry["stored_path"], entry["stored_bytes"])
        if (
            len(compressed) != entry["stored_bytes"]
            or hashlib.sha256(compressed).hexdigest() != entry["stored_sha256"]
        ):
            raise ValueError("stored evidence checksum mismatch")
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        data = decoder.decompress(compressed, expected_bytes + 1)
        if (
            not decoder.eof
            or decoder.unused_data
            or decoder.unconsumed_tail
            or len(data) != expected_bytes
        ):
            raise ValueError("truncated, oversized or concatenated gzip evidence")
    if (
        len(data) != expected_bytes
        or hashlib.sha256(data).hexdigest() != expected_sha256
    ):
        raise ValueError("original evidence length or checksum mismatch")
    return data


def restore(repo, destination):
    repo = repo.resolve(strict=True)
    destination = destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("destination must be a new directory")
    if not destination.parent.is_dir() or any(
        p.is_symlink() for p in destination.parents
    ):
        raise ValueError("destination parent must be an existing regular directory")
    if destination.is_relative_to(repo):
        raise ValueError("destination must be outside the repository")
    outputs = []
    for name, entry in entries(repo).items():
        data = read_verified(
            repo, name, entry["original_bytes"], entry["original_sha256"]
        )
        blob = hashlib.sha1(
            b"blob " + str(len(data)).encode() + b"\0" + data
        ).hexdigest()
        if blob != entry["original_git_blob"]:
            raise ValueError("original Git blob mismatch")
        outputs.append((name, data))
    destination.mkdir(mode=0o700)
    for name, data in outputs:
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(data)
    print(f"Restored {len(outputs)} exact historical evidence files")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    arguments = parser.parse_args()
    restore(Path(__file__).resolve().parents[3], arguments.destination)
