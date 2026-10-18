"""Physically join the original scorer and preserve its complete or partial output."""

import hashlib
import os
import subprocess
import time


def write_original(directory, name, payload):
    path = directory / name
    with path.open("xb", buffering=0) as stream:
        os.chmod(path, 0o600)
        stream.write(payload)
        os.fsync(stream.fileno())
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return hashlib.sha256(payload).hexdigest()


def score(argv, inputs, deadline, directory, stdout_name, stderr_name):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("original training budget before numeric execution")
    try:
        observed = subprocess.run(
            argv, input=inputs, capture_output=True, timeout=remaining, check=False
        )
    except subprocess.TimeoutExpired as error:
        # subprocess.run has killed and physically waited for its own child.
        # Partial bytes remain original evidence; they never become predictions.
        write_original(directory, stdout_name, error.stdout or b"")
        write_original(directory, stderr_name, error.stderr or b"")
        raise
    digest = write_original(directory, stdout_name, observed.stdout)
    write_original(directory, stderr_name, observed.stderr)
    if observed.returncode != 0:
        raise RuntimeError("original scorer failed; raw output retained")
    return observed.stdout, digest
