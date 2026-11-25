"""Invoke the pinned statement-only native CLI without reviving legacy consent."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile

from intake_contract import BLOCKER, Refused, canonical, digest, read_json, require

MAX_OUTPUT = 32768


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
        # Files bound memory even if an incorrectly configured trusted process
        # writes excessive diagnostics. Logs are private and not exported.
        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
            with subprocess.Popen(command, stdin=subprocess.PIPE, stdout=output, stderr=errors,
                                  pass_fds=(fd,), env={"PATH": os.defpath, "LANG": "C"}) as proc:
                try:
                    proc.communicate(raw, timeout=timeout)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                    raise Refused("native statement timeout")
            output.seek(0); errors.seek(0)
            answer, error = output.read(MAX_OUTPUT + 1), errors.read(MAX_OUTPUT + 1)
            require(len(answer) <= MAX_OUTPUT and len(error) <= MAX_OUTPUT, "native output bound")
        after = os.fstat(fd)
        require((before.st_dev, before.st_ino, before.st_size, before.st_ctime_ns, before.st_mtime_ns)
                == (after.st_dev, after.st_ino, after.st_size, after.st_ctime_ns, after.st_mtime_ns),
                "native changed during statement rendering")
        require(proc.returncode == 0, "native statement rejected")
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
