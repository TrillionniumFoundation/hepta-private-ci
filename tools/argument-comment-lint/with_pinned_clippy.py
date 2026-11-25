#!/usr/bin/env python3
"""Run the original Dylint command with its pinned Clippy source available."""

import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import tomllib

CLIPPY_URL = "https://github.com/rust-lang/rust-clippy"


def pinned_inputs(directory: Path) -> tuple[str, str]:
    manifest = tomllib.loads((directory / "Cargo.toml").read_text(encoding="utf-8"))
    dependency = manifest["dependencies"]["clippy_utils"]
    revision = dependency.get("rev", "")
    if dependency.get("git") != CLIPPY_URL or re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise ValueError("clippy_utils must use the official URL and an exact commit")
    toolchain = tomllib.loads((directory / "rust-toolchain").read_text(encoding="utf-8"))
    channel = toolchain["toolchain"]["channel"]
    if re.fullmatch(r"nightly-[0-9]{4}-[0-9]{2}-[0-9]{2}", channel) is None:
        raise ValueError("the lint toolchain must remain a dated nightly")
    return revision, channel


def git_environment(environment: dict[str, str], mirror: Path | None = None) -> dict[str, str]:
    child = environment.copy()
    for name in list(child):
        if name.startswith("GIT_CONFIG_") or name in {
            "GIT_CONFIG", "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE",
            "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        }:
            del child[name]
    # No persisted credentials or user Git configuration are needed for this
    # public source input. The parent environment and config files are untouched.
    entries = [
        ("credential.helper", ""),
        ("core.askPass", ""),
        ("http.extraHeader", ""),
        ("http.https://github.com/.extraHeader", ""),
    ]
    if mirror is not None:
        entries.append((f"url.{mirror.resolve().as_uri()}.insteadOf", CLIPPY_URL))
    child.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_COUNT=str(len(entries)),
        GIT_TERMINAL_PROMPT="0",
        GIT_ASKPASS="",
        SSH_ASKPASS="",
    )
    for index, (key, value) in enumerate(entries):
        child[f"GIT_CONFIG_KEY_{index}"] = key
        child[f"GIT_CONFIG_VALUE_{index}"] = value
    return child


def prepare_mirror(
    source: str, revision: str, channel: str, mirror: Path, environment: dict[str, str]
) -> None:
    env = git_environment(environment)

    def git(*args: str) -> str:
        completed = subprocess.run(
            ["git", *args], env=env, check=True, capture_output=True, text=True
        )
        return completed.stdout.strip()

    git("init", "--bare", "--quiet", str(mirror))
    # Dylint 5.0.0 hardcodes this local name. It is an alias for the manifest's
    # immutable commit, never a claim that upstream still has a master branch.
    git("-C", str(mirror), "symbolic-ref", "HEAD", "refs/heads/master")
    git(
        "-C", str(mirror), "fetch", "--quiet", "--no-tags", source,
        f"{revision}:refs/heads/master",
    )
    if git("-C", str(mirror), "rev-parse", "refs/heads/master") != revision:
        raise ValueError("the Clippy mirror does not match the pinned commit")
    if git("-C", str(mirror), "rev-parse", "--is-shallow-repository") != "false":
        raise ValueError("Dylint's historical channel lookup requires complete ancestry")
    actual = tomllib.loads(git("-C", str(mirror), "show", f"{revision}:rust-toolchain.toml"))
    if actual["toolchain"]["channel"] != channel:
        raise ValueError("the pinned Clippy commit uses a different nightly")


def main(argv: list[str]) -> int:
    if not argv or argv[0] != "--" or len(argv) == 1:
        raise ValueError("usage: with_pinned_clippy.py -- ORIGINAL_COMMAND [ARG ...]")
    revision, channel = pinned_inputs(Path(__file__).resolve().parent)
    # Keep the mirror alive until the original command and its Dylint build
    # finish. No checkout, lockfile, Rust flags, test selector or tool is changed.
    with tempfile.TemporaryDirectory(prefix="dylint-pinned-clippy-") as temporary:
        mirror = Path(temporary) / "clippy.git"
        prepare_mirror(CLIPPY_URL, revision, channel, mirror, dict(os.environ))
        print(f"Dylint Clippy input: {revision} ({channel})", flush=True)
        completed = subprocess.run(argv[1:], env=git_environment(dict(os.environ), mirror))
        return completed.returncode


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except (KeyError, ValueError, subprocess.CalledProcessError) as error:
        print(f"pinned Clippy preparation failed: {error}", file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            print(error.stderr[-8192:], file=sys.stderr)
        raise SystemExit(1) from error
