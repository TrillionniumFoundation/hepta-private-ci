#!/usr/bin/env python3
"""Bounded, local OS flock mechanism probe; never executes project tests.

Fresh private files and owned children only. The child remains before exec on
purpose; this establishes a possible descriptor lifetime, not the original
macOS CI scheduler or the actual implementation of posix_spawn.
"""
import errno
import fcntl
import json
import os
from pathlib import Path
import select
import signal
import tempfile
import time


def open_file(path):
    return os.open(path, os.O_RDWR | os.O_CLOEXEC)


def contender(path):
    fd = open_file(path)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            if error.errno not in (errno.EAGAIN, errno.EACCES):
                raise
            return "WouldBlock"
        fcntl.flock(fd, fcntl.LOCK_UN)
        return "Acquired"
    finally:
        os.close(fd)


def new_holder(path):
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_CLOEXEC, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    assert contender(path) == "WouldBlock"
    assert fcntl.fcntl(fd, fcntl.F_GETFD) & fcntl.FD_CLOEXEC
    return fd


def duplicate_case(directory, explicit_unlock):
    path = directory / ("dup-unlock" if explicit_unlock else "dup-close")
    holder = new_holder(path)
    duplicate = os.dup(holder)
    try:
        if explicit_unlock:
            fcntl.flock(holder, fcntl.LOCK_UN)
        os.close(holder)
        holder = None
        while_duplicate_open = contender(path)
        expected = "Acquired" if explicit_unlock else "WouldBlock"
        assert while_duplicate_open == expected
        os.fstat(duplicate)
        os.close(duplicate)
        duplicate = None
        after_final_close = contender(path)
        assert after_final_close == "Acquired"
        return {
            "kind": "dup",
            "release": "explicit_unlock_then_close" if explicit_unlock else "close_only",
            "while_duplicate_open": while_duplicate_open,
            "after_final_close": after_final_close,
        }
    finally:
        if holder is not None:
            os.close(holder)
        if duplicate is not None:
            os.close(duplicate)


def wait_owned_child(pid):
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        actual_pid, status = os.waitpid(pid, os.WNOHANG)
        if actual_pid == pid:
            assert os.waitstatus_to_exitcode(status) == 0, status
            return
        time.sleep(0.005)
    raise TimeoutError("owned mechanism child did not exit")


def fork_case(directory, explicit_unlock):
    path = directory / ("fork-unlock" if explicit_unlock else "fork-close")
    holder = new_holder(path)
    ready_read, ready_write = os.pipe()
    release_read, release_write = os.pipe()
    pid = os.fork()
    if pid == 0:
        try:
            os.close(ready_read)
            os.close(release_write)
            os.fstat(holder)
            if not (fcntl.fcntl(holder, fcntl.F_GETFD) & fcntl.FD_CLOEXEC):
                os._exit(3)
            os.write(ready_write, b"R")
            os.close(ready_write)
            if not select.select([release_read], [], [], 5)[0]:
                os._exit(4)
            os.read(release_read, 1)
            os.close(release_read)
            os.close(holder)
            os._exit(0)
        except BaseException:
            os._exit(5)
    os.close(ready_write)
    os.close(release_read)
    reaped = False
    try:
        assert select.select([ready_read], [], [], 5)[0], "child ready deadline"
        assert os.read(ready_read, 1) == b"R"
        if explicit_unlock:
            fcntl.flock(holder, fcntl.LOCK_UN)
        os.close(holder)
        holder = None
        while_child_before_exec = contender(path)
        expected = "Acquired" if explicit_unlock else "WouldBlock"
        assert while_child_before_exec == expected
        actual_pid, _ = os.waitpid(pid, os.WNOHANG)
        assert actual_pid == 0, "child must still own its inherited descriptor"
        os.write(release_write, b"X")
        wait_owned_child(pid)
        reaped = True
        after_child_close = contender(path)
        assert after_child_close == "Acquired"
        return {
            "kind": "fork_before_exec",
            "release": "explicit_unlock_then_close" if explicit_unlock else "close_only",
            "parent_and_child_fd_cloexec": True,
            "owned_child_handshake_confirmed": True,
            "while_child_before_exec": while_child_before_exec,
            "after_child_close": after_child_close,
        }
    finally:
        if holder is not None:
            os.close(holder)
        os.close(ready_read)
        os.close(release_write)
        if not reaped:
            # pid came only from this exact os.fork; never a discovered process.
            actual_pid, _ = os.waitpid(pid, os.WNOHANG)
            if actual_pid == 0:
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)


def main():
    with tempfile.TemporaryDirectory(prefix="hepta-flock-mechanism-") as temporary:
        directory = Path(temporary)
        cases = [
            duplicate_case(directory, False),
            duplicate_case(directory, True),
            fork_case(directory, False),
            fork_case(directory, True),
        ]
    print(json.dumps({
        "scope": "controlled local OS mechanism only; not project Rust or original Mac ARM execution",
        "platform": dict(zip(os.uname()._fields, os.uname())) if hasattr(os.uname(), "_fields") else {
            "sysname": os.uname().sysname, "release": os.uname().release, "machine": os.uname().machine
        },
        "cases": cases,
        "case_count": len(cases),
        "original_mac_failure_cause_proven": False,
        "project_tests_executed": False,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
