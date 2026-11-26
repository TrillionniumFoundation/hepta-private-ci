"""Invoke the pinned statement-only native CLI without reviving legacy consent."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import selectors
import signal
import subprocess
import tempfile
import time

from intake_contract import BLOCKER, Refused, canonical, digest, read_json, require

MAX_OUTPUT = 32768


def _bounded_statement(command, fd, raw, timeout):
    require(type(timeout) in (int, float) and math.isfinite(timeout) and timeout > 0,
            "positive finite native timeout required")
    deadline = time.monotonic() + timeout
    buffers = (bytearray(), bytearray())
    with tempfile.TemporaryFile() as source:
        source.write(raw)
        source.seek(0)
        proc = subprocess.Popen(command, stdin=source, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, pass_fds=(fd,),
                                env={"PATH": os.defpath, "LANG": "C"},
                                start_new_session=True)
        try:
            with selectors.DefaultSelector() as selector:
                for index, pipe in enumerate((proc.stdout, proc.stderr)):
                    os.set_blocking(pipe.fileno(), False)
                    selector.register(pipe, selectors.EVENT_READ, index)
                while True:
                    remaining = deadline - time.monotonic()
                    require(remaining > 0, "native statement timeout")
                    # Observe without reaping: retain the leader PID until its
                    # original process group has received final cancellation.
                    exited = os.waitid(os.P_PID, proc.pid,
                                       os.WEXITED | os.WNOHANG | os.WNOWAIT)
                    if exited is not None and not selector.get_map():
                        break
                    for key, _ in selector.select(min(remaining, 0.05)):
                        target = buffers[key.data]
                        chunk = os.read(key.fd, min(8192, MAX_OUTPUT - len(target) + 1))
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        require(len(target) + len(chunk) <= MAX_OUTPUT, "native output bound")
                        target.extend(chunk)
        finally:
            try:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            finally:
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired as error:
                    raise Refused("native process-group cleanup incomplete") from error
                finally:
                    proc.stdout.close()
                    proc.stderr.close()
        require(proc.returncode == 0, "native statement rejected")
        return bytes(buffers[0])


def invoke(executable, expected_sha256, scope=None, timeout=10):
    """Only the operator chooses the binary; data cannot provide argv or paths."""
    digest(expected_sha256)
    fd = os.open(executable, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_mode & 0o022 == 0,
                "native binary must be a protected regular file")
        with os.fdopen(os.dup(fd), "rb") as stream:
            require(stream.read(4) == b"\x7fELF", "original Linux ELF required")
            stream.seek(0)
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        require(actual == expected_sha256, "native ELF pin changed")
        command = [f"/proc/self/fd/{fd}", "--help" if scope is None else "--print-statement"]
        raw = b"" if scope is None else canonical(scope)
        require(len(raw) <= MAX_OUTPUT, "statement scope too large")
        answer = _bounded_statement(command, fd, raw, timeout)
        after = os.fstat(fd)
        require((before.st_dev, before.st_ino, before.st_size, before.st_ctime_ns, before.st_mtime_ns)
                == (after.st_dev, after.st_ino, after.st_size, after.st_ctime_ns, after.st_mtime_ns),
                "native changed during statement rendering")
        return answer
    finally:
        os.close(fd)


def authorization_status(executable, expected_sha256):
    help_bytes = invoke(executable, expected_sha256)
    require(BLOCKER.encode() in help_bytes and b"--print-statement" in help_bytes,
            "unexpected native interface; source review required")
    return {"schema": "hepta.adoption-closure.native-interface.v2",
            "native_elf_sha256": expected_sha256,
            "help_sha256": hashlib.sha256(help_bytes).hexdigest(),
            "statement_renderer_available": True,
            "original_turn_authorization_available": False,
            "legacy_sqlite_receipt_accepted": False, "blocker": BLOCKER}


def authorize_owner(*unused_args, **unused_kwargs):
    # No arbitrary callback, fixture mode, CLI flag or supplied JSON can turn
    # the current source into the missing protected original-turn verifier.
    raise Refused(BLOCKER)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("native", type=Path)
    parser.add_argument("native_sha256")
    parser.add_argument("--statement", type=Path)
    args = parser.parse_args()
    if args.statement:
        # Exact native bytes stay on the private invoking host, for its own UI.
        os.write(1, invoke(args.native, args.native_sha256, read_json(args.statement)))
    else:
        print(json.dumps(authorization_status(args.native, args.native_sha256), sort_keys=True))


if __name__ == "__main__":
    main()
