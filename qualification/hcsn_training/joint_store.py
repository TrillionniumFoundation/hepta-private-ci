"""Held-directory Joint journal. Partial writes remain; no recovery overwrites."""

from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import stat
import sys
import time

from qualification.hcsn_training.joint_protocol import LAYOUT, TERMINAL_CAP, encoded, require, root_identity


def file_identity(value):
    return (value.st_dev, value.st_ino, value.st_mode, value.st_uid, value.st_nlink,
            value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def directory_identity(value):
    return (value.st_dev, value.st_ino, value.st_mode, value.st_uid)


def leaf(name):
    require(type(name) is str and name not in ("", ".", "..")
            and "/" not in name and "\0" not in name, "relative leaf required")
    return name


def read_relative(fd, name, limit):
    named = os.stat(leaf(name), dir_fd=fd, follow_symlinks=False)
    require(stat.S_ISREG(named.st_mode) and stat.S_IMODE(named.st_mode) == 0o600
            and named.st_uid == os.geteuid() and named.st_nlink == 1
            and 0 <= named.st_size <= limit, "private bounded regular record")
    opened = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=fd)
    try:
        before = file_identity(named)
        require(file_identity(os.fstat(opened)) == before, "record open race")
        data = bytearray()
        while len(data) <= limit:
            part = os.read(opened, min(65536, limit + 1 - len(data)))
            if not part:
                break
            data.extend(part)
        require(len(data) == named.st_size and file_identity(os.fstat(opened)) == before
                and file_identity(os.stat(name, dir_fd=fd, follow_symlinks=False)) == before,
                "record changed during read")
        return bytes(data)
    finally:
        os.close(opened)


class Root:
    """An already provisioned host root, never selected by a task payload."""

    def __init__(self, path, expected):
        self.path, self.expected = Path(path), root_identity(expected)
        self.fd = None
        self.children = []
        require(sys.platform == "linux" and self.path.is_absolute()
                and self.path.resolve(strict=True) == self.path, "canonical Linux provider root")
        self.fd = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            self.check()
        except BaseException:
            self.close()
            raise

    def check(self):
        require(self.path.resolve(strict=True) == self.path, "provider root redirected")
        opened, named = os.fstat(self.fd), self.path.lstat()
        expected = self.expected
        require(stat.S_ISDIR(opened.st_mode) and stat.S_IMODE(opened.st_mode) == 0o700
                and opened.st_uid == os.geteuid() == expected["uid"]
                and (opened.st_dev, opened.st_ino) == (expected["device"], expected["inode"])
                and directory_identity(opened) == directory_identity(named), "provider root incarnation changed")
        require(read_relative(self.fd, "layout.json", 256) == LAYOUT, "provider layout not provisioned")

    def child(self, name, create=False, existing_ok=False):
        return Directory(self, name, create, existing_ok)

    def close(self):
        for child in reversed(self.children):
            if child.fd is not None:
                os.close(child.fd)
                child.fd = None
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class Directory:
    def __init__(self, parent, name, create=False, existing_ok=False):
        self.parent, self.name = parent, leaf(name)
        self.root = parent if isinstance(parent, Root) else parent.root
        self.path = parent.path / name
        self.fd = None
        parent.check()
        if create:
            try:
                os.mkdir(name, 0o700, dir_fd=parent.fd)
                os.fsync(parent.fd)
            except FileExistsError:
                if not existing_ok:
                    raise
        self.fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent.fd)
        self.identity = directory_identity(os.fstat(self.fd))
        self.root.children.append(self)
        self.check()

    def check(self):
        self.parent.check()
        opened = os.fstat(self.fd)
        named = os.stat(self.name, dir_fd=self.parent.fd, follow_symlinks=False)
        require(stat.S_ISDIR(opened.st_mode) and stat.S_IMODE(opened.st_mode) == 0o700
                and opened.st_uid == os.geteuid()
                and self.identity == directory_identity(opened) == directory_identity(named)
                == directory_identity(self.path.lstat())
                and self.path.resolve(strict=True) == self.path, "journal directory changed")

    def child(self, name, create=False, existing_ok=False):
        return Directory(self, name, create, existing_ok)

    def read(self, name, limit=TERMINAL_CAP):
        self.check()
        raw = read_relative(self.fd, name, limit)
        self.check()
        return raw

    def exists(self, name):
        self.check()
        try:
            os.stat(leaf(name), dir_fd=self.fd, follow_symlinks=False)
            result = True
        except FileNotFoundError:
            result = False
        self.check()
        return result

    def names(self, cap=64):
        self.check()
        names = []
        with os.scandir(self.fd) as entries:
            for entry in entries:
                require(len(names) < cap, "directory entry bound")
                names.append(entry.name)
        self.check()
        return sorted(names)

    def write(self, name, value):
        raw = value if type(value) is bytes else encoded(value)
        require(len(raw) <= TERMINAL_CAP, "journal byte bound")
        self.check()
        fd = os.open(leaf(name), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=self.fd)
        try:
            offset = 0
            while offset < len(raw):
                count = os.write(fd, raw[offset:])
                require(count > 0, "short record write")
                offset += count
            os.fsync(fd)
            info = os.fstat(fd)
            require(info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o600
                    and info.st_nlink == 1 and info.st_size == len(raw)
                    and file_identity(info) == file_identity(os.stat(name, dir_fd=self.fd, follow_symlinks=False)),
                    "new record changed")
        finally:
            os.close(fd)
        os.fsync(self.fd)
        require(self.read(name) == raw, "record readback")

    def open_log(self, name):
        self.check()
        require(name in ("runner.stdout", "runner.stderr", "worker.stdout", "worker.stderr"), "fixed log")
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=self.fd)
        info = os.fstat(fd)
        try:
            require(stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600
                    and info.st_uid == os.geteuid() and info.st_nlink == 1
                    and file_identity(info) == file_identity(os.stat(name, dir_fd=self.fd, follow_symlinks=False)),
                    "private log identity")
        except BaseException:
            os.close(fd)
            raise
        os.fsync(self.fd)
        self.check()
        return os.fdopen(fd, "wb", buffering=0)


@contextmanager
def dispatch_lock(root):
    root.check()
    try:
        fd = os.open("dispatch.lock", os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=root.fd)
        os.fsync(root.fd)
    except FileExistsError:
        fd = os.open("dispatch.lock", os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=root.fd)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and stat.S_IMODE(before.st_mode) == 0o600
                and before.st_uid == os.geteuid() and before.st_nlink == 1, "private dispatch lock")
        deadline = time.monotonic() + 2
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                require(time.monotonic() < deadline, "dispatch lock deadline")
                time.sleep(0.01)
        root.check()
        require(file_identity(before) == file_identity(os.stat("dispatch.lock", dir_fd=root.fd, follow_symlinks=False)),
                "dispatch lock rebound")
        yield
        root.check()
    finally:
        os.close(fd)
