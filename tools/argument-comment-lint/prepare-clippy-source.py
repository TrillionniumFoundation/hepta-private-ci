#!/usr/bin/env python3
"""Prepare the exact Clippy repository used by Dylint's extra-symbol builder."""

import argparse
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import parse_qs, urlsplit


CLIPPY_REPOSITORY = "https://github.com/rust-lang/rust-clippy"


def capture(command: list[str], cwd: Path | None = None) -> str:
    return subprocess.check_output(command, cwd=cwd, text=True).strip()


def channel(source: str) -> str:
    match = re.search(r'^channel\s*=\s*"(nightly-\d{4}-\d{2}-\d{2})"\s*$', source, re.M)
    if match is None:
        raise ValueError("expected a pinned nightly channel")
    return match.group(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--github-env", type=Path)
    args = parser.parse_args()

    lint_root = Path(__file__).resolve().parent
    metadata = json.loads(
        capture(
            [
                "cargo", "metadata", "--offline", "--locked", "--no-deps",
                "--format-version=1", "--manifest-path", str(lint_root / "Cargo.toml"),
            ],
            cwd=lint_root,
        )
    )
    package = next(p for p in metadata["packages"] if p["name"] == "argument_comment_lint")
    dependency = next(d for d in package["dependencies"] if d["name"] == "clippy_utils")
    source = dependency["source"]
    if not source.startswith("git+"):
        raise ValueError("clippy_utils must use the pinned upstream Git repository")
    url = urlsplit(source.removeprefix("git+"))
    revisions = parse_qs(url.query)
    if f"{url.scheme}://{url.netloc}{url.path}" != CLIPPY_REPOSITORY or set(revisions) != {"rev"}:
        raise ValueError("unexpected Clippy repository or revision selector")
    revision = revisions["rev"][0]
    if len(revisions["rev"]) != 1 or re.fullmatch(r"[0-9a-f]{40}", revision) is None or url.fragment:
        raise ValueError("clippy_utils requires a full immutable commit ID")

    destination = args.destination.resolve()
    if not destination.exists():
        subprocess.run(["git", "init", "--initial-branch=main", str(destination)], check=True)
        subprocess.run(["git", "remote", "add", "origin", CLIPPY_REPOSITORY], cwd=destination, check=True)
        # Dylint's revision iterator emits a channel only after observing its predecessor.
        subprocess.run(["git", "fetch", "--depth=2", "--no-tags", "origin", revision], cwd=destination, check=True)
        subprocess.run(["git", "checkout", "--detach", revision], cwd=destination, check=True)

    if capture(["git", "rev-parse", "HEAD"], destination) != revision:
        raise ValueError("existing Clippy checkout has a different revision")
    if capture(["git", "status", "--porcelain", "--untracked-files=all"], destination):
        raise ValueError("Clippy checkout must be clean")
    expected_channel = channel((lint_root / "rust-toolchain").read_text())
    if channel(capture(["git", "show", "HEAD:rust-toolchain.toml"], destination)) != expected_channel:
        raise ValueError("Clippy commit and lint toolchain do not match")
    if channel(capture(["git", "show", "HEAD^:rust-toolchain.toml"], destination)) >= expected_channel:
        raise ValueError("pin a Clippy toolchain-update commit with the preceding channel available")

    if args.github_env is not None:
        if "\n" in str(destination) or "\r" in str(destination):
            raise ValueError("Clippy checkout path cannot contain line breaks")
        with args.github_env.open("a", encoding="utf-8") as output:
            output.write(f"DYLINT_CLIPPY_REPO={destination}\n")
    print(json.dumps({"path": str(destination), "revision": revision, "channel": expected_channel}))


if __name__ == "__main__":
    main()
