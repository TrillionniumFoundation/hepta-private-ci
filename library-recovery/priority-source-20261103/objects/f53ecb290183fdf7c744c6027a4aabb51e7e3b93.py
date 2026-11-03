"""Bounded OS semantic experiment; never opens repository/product stores."""
import fcntl
import json
import os
import select
import signal
import sys
import tempfile


def receive(fd, expected):
    if not select.select([fd], [], [], 3)[0]:
        raise TimeoutError("child barrier deadline")
    actual = os.read(fd, 1)
    assert actual == expected, (actual, expected)


with tempfile.TemporaryDirectory(prefix="taskflow-flock-semantics-") as directory:
    path = os.path.join(directory, "own-fixture")
    owner = open(path, "w+b")
    assert not os.get_inheritable(owner.fileno())
    fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
    control_r, control_w = os.pipe()
    status_r, status_w = os.pipe()
    # Only test-control pipes survive exec; the lock-owning file remains CLOEXEC.
    os.set_inheritable(control_r, True)
    os.set_inheritable(status_w, True)
    child = os.fork()
    if child == 0:
        signal.alarm(6)
        os.close(control_w)
        os.close(status_r)
        os.write(status_w, b"F")
        if os.read(control_r, 1) != b"E":
            os._exit(2)
        program = (
            "import os,signal; signal.alarm(6); "
            f"os.write({status_w},b'E'); "
            f"assert os.read({control_r},1)==b'X'"
        )
        os.execv(sys.executable, [sys.executable, "-c", program])
    os.close(control_r)
    os.close(status_w)
    reaped = False
    try:
        receive(status_r, b"F")
        owner.close()
        with open(path, "r+b") as contender:
            try:
                fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                before_exec = "Busy"
            else:
                raise AssertionError("inherited live description did not retain lock")
            os.write(control_w, b"E")
            receive(status_r, b"E")
            assert os.waitpid(child, os.WNOHANG) == (0, 0), "child must remain alive"
            fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
            after_exec = "Acquired"
        os.write(control_w, b"X")
        pidfd = os.pidfd_open(child)
        try:
            assert select.select([pidfd], [], [], 3)[0], "child exit deadline"
        finally:
            os.close(pidfd)
        pid, status = os.waitpid(child, 0)
        reaped = True
        assert pid == child and os.waitstatus_to_exitcode(status) == 0
        print(json.dumps({
            "file_close_on_exec": True,
            "parent_closed_owner_with_child_preexec": before_exec,
            "child_exec_closed_file_but_child_still_alive": after_exec,
            "child_exit": 0,
            "scope": "Linux OS lock/fork/CLOEXEC semantics only; not a Rust/CI race reproduction",
            "production_store_access": False,
        }, indent=2))
    finally:
        owner.close()
        if not reaped:
            try:
                os.kill(child, signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.waitpid(child, 0)
        os.close(control_w)
        os.close(status_r)
