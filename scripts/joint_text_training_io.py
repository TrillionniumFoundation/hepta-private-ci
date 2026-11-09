"""Bounded file snapshots and create-only outputs for one unsigned Joint worker.

These checks bind bytes observed by this process. They do not authenticate the
process, its interpreter, a job scheduler, or the future use of an artifact.
"""

from dataclasses import dataclass
import os
from pathlib import Path
import stat

from scripts.joint_text_training_contract import (
    ABSENT_SOURCES,
    ContractError,
    OUTPUT_FILES,
    SOURCE_FILES,
    require,
    sha,
    source_digest,
)

SOURCE_FILE_CAP = 256 * 1024


def identity(value):
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def physical(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve(strict=True) == path, "physical_path")
    return path


@dataclass(frozen=True)
class Snapshot:
    path: Path
    raw: bytes
    stat_identity: tuple

    def source_row(self, relative):
        return {"path": relative, "bytes": len(self.raw), "sha256": sha(self.raw)}

    def check(self):
        after = read_snapshot(self.path, len(self.raw))
        require(
            self.stat_identity == after.stat_identity and self.raw == after.raw,
            "input_file_changed",
        )


def read_snapshot(path, limit):
    """Read a bounded regular file while binding the path and opened inode."""
    path = physical(path)
    before = path.lstat()
    require(
        stat.S_ISREG(before.st_mode) and 0 <= before.st_size <= limit,
        "regular_file_bound",
    )
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        require(identity(os.fstat(fd)) == identity(before), "file_open_race")
        data = bytearray()
        while len(data) <= limit:
            part = os.read(fd, min(65536, limit + 1 - len(data)))
            if not part:
                break
            data.extend(part)
        require(len(data) == before.st_size and len(data) <= limit, "file_read_bound")
        require(
            identity(os.fstat(fd)) == identity(before) == identity(path.lstat()),
            "file_read_race",
        )
        return Snapshot(path, bytes(data), identity(before))
    finally:
        os.close(fd)


def require_absent(path):
    try:
        Path(path).lstat()
    except FileNotFoundError:
        return
    raise ContractError("unexpected_source_initializer")


class SourceClosure:
    """Capture the seven repository sources and four absent initializers."""

    def __init__(self, root):
        self.root = physical(root)
        self.files = {
            name: read_snapshot(self.root / name, SOURCE_FILE_CAP)
            for name in SOURCE_FILES
        }
        for name in ABSENT_SOURCES:
            require_absent(self.root / name)
        self.rows = [self.files[name].source_row(name) for name in sorted(self.files)]
        self.absent = sorted(ABSENT_SOURCES)
        self.digest = source_digest(self.rows, self.absent)

    def check(self):
        for snapshot in self.files.values():
            snapshot.check()
        for name in self.absent:
            require_absent(self.root / name)


class OutputStore:
    """One new private directory, held by fd, with exclusive fixed-name files.

    An interrupted write is retained. No resume, replacement, unlink, rename,
    or retry is attempted. A failed marker is never a candidate observation.
    """

    def __init__(self, path):
        self.path = Path(path)
        require(
            self.path.is_absolute() and self.path.name not in ("", ".", ".."),
            "output_path",
        )
        parent = physical(self.path.parent)
        self.parent_fd = os.open(
            parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        )
        parent_value = os.fstat(self.parent_fd)
        self.parent_identity = (
            parent_value.st_dev,
            parent_value.st_ino,
            parent_value.st_mode,
            parent_value.st_uid,
        )
        self.fd = None
        self.written = {}
        try:
            os.mkdir(self.path.name, 0o700, dir_fd=self.parent_fd)
            self.fd = os.open(
                self.path.name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=self.parent_fd,
            )
            value = os.fstat(self.fd)
            require(
                stat.S_IMODE(value.st_mode) == 0o700 and value.st_uid == os.geteuid(),
                "private_output_directory",
            )
            self.directory_identity = (
                value.st_dev,
                value.st_ino,
                value.st_mode,
                value.st_uid,
            )
            self.check_directory()
            os.fsync(self.parent_fd)
        except BaseException:
            self.close()
            raise

    def check_directory(self):
        opened = os.fstat(self.fd)
        named = os.stat(self.path.name, dir_fd=self.parent_fd, follow_symlinks=False)
        absolute = self.path.lstat()
        parent = self.path.parent.lstat()
        require(
            self.parent_identity
            == (parent.st_dev, parent.st_ino, parent.st_mode, parent.st_uid),
            "output_parent_changed",
        )
        require(
            self.directory_identity
            == (opened.st_dev, opened.st_ino, opened.st_mode, opened.st_uid)
            == (named.st_dev, named.st_ino, named.st_mode, named.st_uid)
            == (absolute.st_dev, absolute.st_ino, absolute.st_mode, absolute.st_uid),
            "output_directory_changed",
        )
        require(self.path.resolve(strict=True) == self.path, "output_directory_rebound")

    def write(self, name, raw):
        require(name in OUTPUT_FILES and type(raw) is bytes, "output_inventory")
        self.check_directory()
        fd = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=self.fd,
        )
        try:
            offset = 0
            while offset < len(raw):
                count = os.write(fd, raw[offset:])
                require(count > 0, "output_short_write")
                offset += count
            os.fsync(fd)
            value = os.fstat(fd)
            require(
                stat.S_ISREG(value.st_mode)
                and value.st_nlink == 1
                and stat.S_IMODE(value.st_mode) == 0o600
                and value.st_size == len(raw),
                "output_file_identity",
            )
            require(
                identity(value)
                == identity(os.stat(name, dir_fd=self.fd, follow_symlinks=False)),
                "output_file_rebound",
            )
            self.written[name] = (identity(value), sha(raw))
        finally:
            os.close(fd)
        os.fsync(self.fd)
        self.check_directory()

    def read(self, name):
        require(name in self.written, "uncommitted_output")
        self.check_directory()
        expected, digest = self.written[name]
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=self.fd)
        try:
            require(identity(os.fstat(fd)) == expected, "output_changed")
            data = bytearray()
            limit = expected[4]
            while len(data) <= limit:
                part = os.read(fd, min(65536, limit + 1 - len(data)))
                if not part:
                    break
                data.extend(part)
            require(len(data) == limit and sha(data) == digest, "output_byte_mismatch")
            require(
                identity(os.fstat(fd))
                == expected
                == identity(os.stat(name, dir_fd=self.fd, follow_symlinks=False)),
                "output_read_race",
            )
            return bytes(data)
        finally:
            os.close(fd)

    def verify_names(self, names):
        self.check_directory()
        require(
            set(os.listdir(self.fd)) == set(names) == set(self.written),
            "output_closed_set",
        )
        for name in names:
            self.read(name)

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        if self.parent_fd is not None:
            os.close(self.parent_fd)
            self.parent_fd = None
