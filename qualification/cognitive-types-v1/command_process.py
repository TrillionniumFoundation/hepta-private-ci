"""Bounded POSIX capture for the existing qualification and mutation runner.

Only the parent owns the log file. A zero leader exit does not prove completion
while descendants remain. This is process-group cleanup, not an OS sandbox for
hostile commands that deliberately escape their session or modify evidence.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
import selectors
import signal
import subprocess
import time

CAPTURE_VERSION = 1
MAX_LOG_BYTES = 64 * 1024 * 1024
CHUNK_BYTES = 64 * 1024
CLEANUP_SECONDS = 5


class CaptureError(ValueError):
    """The command did not produce a closed, complete bounded observation."""


def group_exists(pid: int) -> bool:
    try:
        os.killpg(pid, 0)
    except ProcessLookupError:
        return False
    return True


def closed_capture(record: dict) -> bool:
    """Validate the exact process/log facts required for a passing command."""
    return (type(record.get("capture_version")) is int
            and record["capture_version"] == CAPTURE_VERSION
            and record.get("log_complete") is True
            and record.get("process_group_closed") is True
            and type(record.get("log_limit_bytes")) is int
            and record["log_limit_bytes"] == MAX_LOG_BYTES
            and type(record.get("log_bytes")) is int
            and 0 <= record["log_bytes"] <= MAX_LOG_BYTES)


def capture_command(argv: list[str], cwd: Path, log: Path,
                    timeout: float, maximum: int = MAX_LOG_BYTES) -> dict:
    if os.name != "posix":
        raise CaptureError("qualification capture requires the selected POSIX host")
    if (type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0
            or type(maximum) is not int or not 0 < maximum <= MAX_LOG_BYTES):
        raise CaptureError("invalid command deadline or log budget")
    deadline = time.monotonic() + timeout
    process = None
    size = 0
    complete = False
    closed = False
    code = None
    error = None
    # Exclusive creation preserves previous evidence and refuses symlink aliases.
    # The child receives a pipe, never a writable descriptor for this file.
    with log.open("xb", buffering=0) as stream:
        try:
            process = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       start_new_session=True)
            pipe = process.stdout
            assert pipe is not None
            os.set_blocking(pipe.fileno(), False)
            with selectors.DefaultSelector() as selector:
                selector.register(pipe, selectors.EVENT_READ)
                while selector.get_map() or process.poll() is None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise CaptureError("command deadline exceeded")
                    code = process.poll()
                    if code is not None and group_exists(process.pid):
                        raise CaptureError("command leader exited with residual descendants")
                    for key, _ in selector.select(min(remaining, 0.05)):
                        try:
                            chunk = os.read(key.fd, CHUNK_BYTES)
                        except BlockingIOError:
                            continue
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        remaining_bytes = maximum - size
                        kept = chunk[:remaining_bytes]
                        # FileIO.write may legally perform a partial write.
                        view = memoryview(kept)
                        while view:
                            written = stream.write(view)
                            if not written:
                                raise CaptureError("command log write made no progress")
                            size += written
                            view = view[written:]
                        if len(chunk) > remaining_bytes:
                            raise CaptureError("command log byte budget exceeded; retained prefix only")
                code = process.wait(timeout=CLEANUP_SECONDS)
                if group_exists(process.pid):
                    raise CaptureError("command left a process group after output EOF")
                complete = True
                closed = True
                if code < 0:
                    raise CaptureError("command terminated by a signal")
        except (OSError, CaptureError, subprocess.SubprocessError) as exc:
            error = f"{type(exc).__name__}: {exc}"
        finally:
            if process is not None:
                if not closed:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    except OSError as exc:
                        error = f"cleanup failed: {type(exc).__name__}: {exc}"
                    try:
                        process.wait(timeout=CLEANUP_SECONDS)
                    except subprocess.TimeoutExpired:
                        error = "cleanup deadline exceeded"
                    # A killed orphan may remain a zombie until its adopter
                    # reaps it. Do not mislabel that unresolved group as closed.
                    closed = not group_exists(process.pid)
                if process.stdout is not None:
                    process.stdout.close()
            os.fsync(stream.fileno())
    status = ("infrastructure_invalid" if error is not None or not complete or not closed
              else "passed" if code == 0 else "failed")
    return {"status": status, "exit_code": code, "error": error,
            "capture_version": CAPTURE_VERSION, "log_complete": complete,
            "process_group_closed": closed, "log_bytes": size,
            "log_limit_bytes": maximum}
