"""Hermetic Git reads for engineering admission and evidence verification."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

from .control_plane import EngineeringError

DEFAULT_MAX_OUTPUT_BYTES = 1_048_576


def git_environment() -> dict[str, str]:
    # Git environment overrides can redirect -C reads or inject configuration.
    # Exact-source admission must derive identity from the nominated repository.
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
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


def guard_git_status(root: Path, args: tuple[str, ...]) -> None:
    if not args or args[0] != "status":
        return
    # A worktree refresh can execute clean/process filters selected by tracked
    # attributes. Such repositories need an isolated adapter, not an admission
    # read on the controller host. Includes are part of the local configuration.
    try:
        configured = subprocess.run(
            ["git", "-C", str(root), "config", "--local", "--includes",
             "--name-only", "--get-regexp", r"^filter\..*\.(clean|process)$"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=git_environment(), timeout=30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise EngineeringError("git_read_failed") from None
    if (
        configured.returncode not in {0, 1}
        or len(configured.stdout) > DEFAULT_MAX_OUTPUT_BYTES
        or len(configured.stderr) > DEFAULT_MAX_OUTPUT_BYTES
    ):
        raise EngineeringError("git_read_failed")
    if configured.stdout:
        raise EngineeringError("repository_git_filter_unsupported")


def run_git_bytes(
    root: Path,
    *args: str,
    maximum_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    timeout_seconds: int = 30,
) -> bytes:
    guard_git_status(root, args)
    try:
        result = subprocess.run(
            [
                "git", "-c", "core.fsmonitor=false",
                "-c", "core.untrackedCache=false", "-C", str(root), *args,
            ],
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
