"""Hermetic Git reads for engineering admission and evidence verification."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

from .control_plane import EngineeringError

DEFAULT_MAX_OUTPUT_BYTES = 1_048_576


def git_environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
        }
    )
    return environment


def run_git_bytes(
    root: Path,
    *args: str,
    maximum_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    timeout_seconds: int = 30,
) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=git_environment(),
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise EngineeringError("git_read_failed") from None
    if (
        result.returncode != 0
        or len(result.stdout) > maximum_output_bytes
        or len(result.stderr) > maximum_output_bytes
    ):
        raise EngineeringError("git_read_failed")
    return result.stdout


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
