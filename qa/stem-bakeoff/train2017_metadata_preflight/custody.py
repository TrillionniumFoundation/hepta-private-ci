"""Pinned read-only files and bounded exact COCO ZIP-member custody."""

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path, PurePosixPath
import stat
from bounded_json import StreamJSON, require
from profile import MEMBERS


def signature(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def verify_bytes(stream, size, digest):
    computed, read = hashlib.sha256(), 0
    while chunk := stream.read(min(1024**2, size + 1 - read)):
        read += len(chunk)
        require(read <= size, "source grew during hash")
        computed.update(chunk)
    require(
        read == size and computed.hexdigest() == digest,
        "source byte/hash pin mismatch",
    )


@contextmanager
def pinned_file(path, size, digest):
    path = Path(path).absolute()
    require(
        not any(p.is_symlink() for p in (path, *path.parents)), "symlink source path"
    )
    before = path.stat()
    require(
        stat.S_ISREG(before.st_mode)
        and before.st_nlink == 1
        and before.st_size == size,
        "source must be exact-size unaliased regular file",
    )
    fd = os.open(
        path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    )
    with os.fdopen(fd, "rb") as stream:
        require(
            signature(before) == signature(os.fstat(stream.fileno())),
            "source changed on open",
        )
        verify_bytes(stream, size, digest)
        stream.seek(0)
        yield stream
        # Bypass buffered reads and timestamp granularity when checking final bytes.
        with os.fdopen(os.dup(stream.fileno()), "rb", buffering=0) as verify:
            verify.seek(0)
            verify_bytes(verify, size, digest)
        require(
            signature(before)
            == signature(os.fstat(stream.fileno()))
            == signature(path.stat()),
            "source changed during preflight",
        )


def member_records(archive, name, arrays, receipts):
    full = "annotations/" + name + ".json"
    expected_bytes, compressed_bytes, expected_sha, cap = MEMBERS[name]
    entries = [v for v in archive.infolist() if v.filename == full]
    require(len(entries) == 1, "missing or duplicate ZIP member")
    entry, path = entries[0], PurePosixPath(full)
    require(
        not path.is_absolute() and ".." not in path.parts and "\\" not in full,
        "unsafe ZIP member name",
    )
    require(
        not entry.is_dir()
        and stat.S_IFMT(entry.external_attr >> 16) in (0, stat.S_IFREG)
        and not entry.flag_bits & 1,
        "non-regular or encrypted ZIP member",
    )
    require(
        0 < entry.file_size == expected_bytes <= cap
        and entry.compress_size == compressed_bytes,
        "ZIP member size/profile mismatch",
    )
    with archive.open(entry) as stream:
        parser = StreamJSON(stream, cap)
        yield from parser.items(arrays)
        require(
            parser.total_bytes == expected_bytes
            and parser.sha256.hexdigest() == expected_sha,
            "JSON member byte/hash pin mismatch",
        )
        receipts[name] = {
            "member": full,
            "bytes": parser.total_bytes,
            "sha256": parser.sha256.hexdigest(),
            "compressed_bytes": entry.compress_size,
            "max_parser_buffer_chars": parser.max_buffer_chars,
        }
