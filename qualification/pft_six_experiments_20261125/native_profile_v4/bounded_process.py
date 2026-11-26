"""Bound one registered Linux child; retain leader PID until group cancellation."""
import os
import selectors
import signal
import subprocess
import time

from profile_io import Refused, require

MAX_CHILD_OUTPUT = 32768


def run_child(command):
    """The caller fixes argv; no shell, communicate, preexec_fn or early reap."""
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, start_new_session=True,
                               env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    output = {"stdout": bytearray(), "stderr": bytearray()}
    deadline = time.monotonic() + 55
    try:
        with selectors.DefaultSelector() as selector:
            for name, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, name)
            while True:
                remaining = deadline - time.monotonic()
                require(remaining > 0, "cold numeric child timeout")
                exited = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                if exited is not None and not selector.get_map():
                    break
                for key, _ in selector.select(min(remaining, .2)):
                    block = os.read(key.fd, min(65536, MAX_CHILD_OUTPUT - len(output[key.data]) + 1))
                    if not block:
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                        continue
                    output[key.data].extend(block)
                    require(len(output[key.data]) <= MAX_CHILD_OUTPUT, "cold numeric child output limit")
    finally:
        try:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        finally:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired as error:
                raise Refused("cold numeric process-group cleanup incomplete") from error
            finally:
                for stream in (process.stdout, process.stderr):
                    if not stream.closed:
                        stream.close()
    require(process.returncode == 0,
            "cold numeric child failed: " + output["stderr"].decode(errors="replace"))
    return bytes(output["stdout"])
