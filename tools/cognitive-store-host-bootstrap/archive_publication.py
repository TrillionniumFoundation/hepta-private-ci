#!/usr/bin/env python3
"""Descriptor-retained publication plumbing for the existing cold archive tool.

No authority, signer, database or active-generation pointer lives here. All
writes remain relative to an already opened private directory. A changed name
is a failure, not permission to follow a replacement path. This is not isolation
from an attacker running as the same OS user or changing the mount namespace.
"""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import secrets
import stat


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def inode(metadata: os.stat_result) -> tuple[int, int]:
    return metadata.st_dev, metadata.st_ino


def name_only(name: str) -> None:
    require(isinstance(name, str) and name not in {"", ".", ".."} and
            "/" not in name and "\0" not in name, "invalid directory-relative name")


def open_directory(path: Path) -> int:
    """Open every path component without following symlinks, including parents."""
    require(os.name == "posix" and all(hasattr(os, key) for key in
            ("O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK", "O_CLOEXEC")),
            "publication requires the POSIX descriptor profile")
    require(path.is_absolute() and ".." not in path.parts, "directory must be absolute and normalized")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    descriptor = os.open(path.anchor, flags)
    try:
        for part in path.parts[1:]:
            successor = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = successor
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


class PinnedDirectory:
    def __init__(self, path: Path, descriptor: int):
        self.path = path
        self.fd = descriptor
        self.original = os.fstat(descriptor)
        self.created_files: dict[str, tuple[int, int]] = {}
        self._private(self.original)

    @staticmethod
    def _private(metadata: os.stat_result) -> None:
        require(stat.S_ISDIR(metadata.st_mode) and metadata.st_uid == os.geteuid() and
                metadata.st_mode & 0o077 == 0, "publication directory must remain owned and private")

    @classmethod
    @contextmanager
    def open(cls, path: Path):
        descriptor = open_directory(path)
        try:
            retained = cls(path, descriptor)
            retained.check_current()
            yield retained
        finally:
            os.close(descriptor)

    def check_current(self) -> None:
        current = open_directory(self.path)
        try:
            observed, retained = os.fstat(current), os.fstat(self.fd)
            self._private(observed)
            self._private(retained)
            require(inode(self.original) == inode(observed) == inode(retained),
                    "publication directory identity changed; preserve and reconcile")
        finally:
            os.close(current)

    def absent(self, name: str) -> None:
        name_only(name)
        try:
            os.stat(name, dir_fd=self.fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        raise ValueError("destination exists; reconcile it instead of replaying")

    @contextmanager
    def create_child(self, name: str):
        name_only(name)
        self.check_current()
        os.mkdir(name, mode=0o700, dir_fd=self.fd)
        descriptor = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW |
                             os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=self.fd)
        try:
            child = PinnedDirectory(self.path / name, descriptor)
            self.check_current()
            child.check_current()
            yield child
        finally:
            os.close(descriptor)

    @contextmanager
    def reader(self, name: str, maximum: int):
        name_only(name)
        self.check_current()
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK |
                             os.O_CLOEXEC, dir_fd=self.fd)
        with os.fdopen(descriptor, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            require(stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1 and
                    metadata.st_mode & 0o077 == 0 and metadata.st_uid == os.geteuid() and
                    metadata.st_size <= maximum, "staged image identity, mode or size changed")
            yield stream

    def writer(self, name: str):
        name_only(name)
        self.check_current()
        descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW |
                             os.O_CLOEXEC, 0o600, dir_fd=self.fd)
        self.created_files[name] = inode(os.fstat(descriptor))
        return os.fdopen(descriptor, "wb")

    def unlink_created(self, name: str) -> None:
        name_only(name)
        metadata = os.stat(name, dir_fd=self.fd, follow_symlinks=False)
        require(self.created_files.get(name) == inode(metadata) and
                stat.S_ISREG(metadata.st_mode), "scratch name is no longer the created inode")
        os.unlink(name, dir_fd=self.fd)
        del self.created_files[name]

    @contextmanager
    def scratch(self):
        # Only these private scratch bytes are eligible for cleanup. Published
        # outputs are never recursively removed, even after an ambiguous fsync.
        name = ".cognitive-private-stage-" + secrets.token_hex(16)
        with self.create_child(name) as stage:
            try:
                yield stage
            finally:
                stage._cleanup_scratch()
                try:
                    current = os.stat(name, dir_fd=self.fd, follow_symlinks=False)
                    if inode(current) == inode(stage.original):
                        os.rmdir(name, dir_fd=self.fd)
                except OSError:
                    # A moved, busy or changed scratch directory is retained;
                    # cleanup must not erase a replacement or mask an outcome.
                    pass

    def _cleanup_scratch(self) -> None:
        try:
            # Never walk an unbounded or unknown tree during cleanup.
            with os.scandir(self.fd) as entries:
                names = []
                for entry in entries:
                    if len(names) >= 1 or entry.name != "cognitive_1.sqlite3":
                        return
                    names.append(entry.name)
            for name in names:
                metadata = os.stat(name, dir_fd=self.fd, follow_symlinks=False)
                if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or
                        self.created_files.get(name) != inode(metadata)):
                    return
                self.unlink_created(name)
        except (OSError, ValueError):
            pass
