"""Hermetic Git reads for engineering admission and evidence verification."""

from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

from .control_plane import EngineeringError

DEFAULT_MAX_OUTPUT_BYTES = 1_048_576


def git_environment() -> dict[str, str]:
    # -C does not override GIT_DIR, GIT_WORK_TREE, alternate object stores or
    # environment-injected config. Reads must stay bound to the requested repo.
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("GIT_")
    }
    environment.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_NO_LAZY_FETCH": "1",
            "LC_ALL": "C",
        }
    )
    return environment


def run_git_bytes(
    root: Path,
    *args: str,
    maximum_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    timeout_seconds: int = 30,
    allow_failure: bool = False,
) -> bytes:
    # Capture on disk and enforce the limit while Git runs. PIPE/communicate
    # followed by len() would first allocate an attacker-sized ref/tree listing.
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        process = None
        try:
            process = subprocess.Popen(
                [
                    "git", "-c", "core.fsmonitor=false", "-c",
                    "core.untrackedCache=false", "-C", str(root), *args,
                ],
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                env=git_environment(),
                start_new_session=True,
            )
            deadline = time.monotonic() + timeout_seconds
            while True:
                if (
                    os.fstat(stdout.fileno()).st_size > maximum_output_bytes
                    or os.fstat(stderr.fileno()).st_size > maximum_output_bytes
                ):
                    raise EngineeringError("git_read_failed")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise EngineeringError("git_read_failed")
                try:
                    process.wait(timeout=min(0.05, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue
            if process.returncode != 0 and not allow_failure:
                raise EngineeringError("git_read_failed")
            stdout.seek(0)
            value = stdout.read(maximum_output_bytes + 1)
            if (
                len(value) > maximum_output_bytes
                or os.fstat(stderr.fileno()).st_size > maximum_output_bytes
            ):
                raise EngineeringError("git_read_failed")
            return value
        except (OSError, subprocess.SubprocessError):
            raise EngineeringError("git_read_failed") from None
        finally:
            if process is not None and process.poll() is None:
                try:
                    if os.name == "posix":
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                except OSError:
                    pass
                process.wait(timeout=10)


def run_git(
    root: Path,
    *args: str,
    maximum_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    timeout_seconds: int = 30,
) -> str:
    try:
        return run_git_bytes(
            root,
            *args,
            maximum_output_bytes=maximum_output_bytes,
            timeout_seconds=timeout_seconds,
        ).decode("utf-8").strip()
    except UnicodeDecodeError:
        raise EngineeringError("git_read_failed") from None


def normal_remote(value: str) -> str:
    value = value.strip().removesuffix(".git").removesuffix("/")
    if value.startswith("git@github.com:"):
        return value.removeprefix("git@github.com:")
    for prefix in ("https://github.com/", "http://github.com/"):
        if value.startswith(prefix):
            return value.removeprefix(prefix)
    return value
