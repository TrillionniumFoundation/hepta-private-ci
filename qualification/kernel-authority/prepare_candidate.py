#!/usr/bin/env python3
"""Prepare an exact or deterministic merge candidate in a disposable checkout."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess


def git(*args: str, env: dict[str, str] | None = None) -> str:
    return subprocess.run(
        ["git", "-c", "core.fsmonitor=false", *args],
        check=True,
        text=True,
        capture_output=True,
        env=env,
    ).stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode", choices=("exact-head", "synthetic-merge"), required=True
    )
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.base_sha):
        parser.error("base-sha must be an exact commit, not a mutable branch")
    root = Path(git("rev-parse", "--show-toplevel")).resolve()
    output = args.output.resolve()
    if output.is_relative_to(root):
        parser.error("evidence output must live outside the source checkout")
    if git("status", "--porcelain"):
        parser.error("candidate checkout must be clean")
    source = git("rev-parse", "HEAD")
    base = git("rev-parse", "--verify", f"{args.base_sha}^{{commit}}")
    if args.mode == "synthetic-merge":
        branch = subprocess.run(
            ["git", "symbolic-ref", "-q", "HEAD"], capture_output=True
        )
        if branch.returncode == 0:
            parser.error("synthetic merge requires a disposable detached checkout")
        tree = git("merge-tree", "--write-tree", base, source).splitlines()[0]
        env = dict(
            os.environ,
            GIT_AUTHOR_NAME="Hepta Qualification",
            GIT_AUTHOR_EMAIL="qualification@hepta.invalid",
            GIT_COMMITTER_NAME="Hepta Qualification",
            GIT_COMMITTER_EMAIL="qualification@hepta.invalid",
            GIT_AUTHOR_DATE="2000-01-01T00:00:00Z",
            GIT_COMMITTER_DATE="2000-01-01T00:00:00Z",
        )
        message = f"kernel.authority qualification only\nsource={source}\nbase={base}"
        candidate = git(
            "commit-tree", tree, "-p", base, "-p", source, "-m", message, env=env
        )
        git("checkout", "--detach", candidate)
    identity = {
        "schema": "hepta.kernel-authority-candidate.v1",
        "mode": args.mode,
        "sourceCommit": source,
        "baseCommit": base,
        "candidateCommit": git("rev-parse", "HEAD"),
        "candidateTree": git("rev-parse", "HEAD^{tree}"),
        "activationGranted": False,
        "releaseGranted": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(identity, sort_keys=True, indent=2) + "\n")
    print(json.dumps(identity, sort_keys=True))


if __name__ == "__main__":
    main()
