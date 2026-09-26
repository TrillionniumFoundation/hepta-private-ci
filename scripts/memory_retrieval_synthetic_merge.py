#!/usr/bin/env python3
"""Create a deterministic, ordered-parent qualification commit; never move refs."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import subprocess

SHA = re.compile(r"[0-9a-f]{40}\Z")


def synthetic_merge(root: Path, base: str, source: str) -> tuple[str, str]:
    if not SHA.fullmatch(base) or not SHA.fullmatch(source):
        raise ValueError("base and source must be exact lowercase Git object IDs")
    if base == source:
        raise ValueError("synthetic merge requires distinct ordered parents")
    def git(*args: str, env: dict | None = None, input: str | None = None) -> str:
        return subprocess.check_output(["git", "-C", str(root), *args], env=env,
                                       input=input, text=True).strip()
    for parent in (base, source):
        if git("cat-file", "-t", parent) != "commit":
            raise ValueError("parent is not a commit")
    # merge-tree exits nonzero on conflict; its output is never a green receipt.
    tree = git("-c", "merge.renormalize=false", "merge-tree", "--write-tree", base, source).splitlines()[0]
    if not SHA.fullmatch(tree) or git("cat-file", "-t", tree) != "tree":
        raise ValueError("invalid merge-tree result")
    epoch = max(int(git("show", "-s", "--format=%ct", parent)) for parent in (base, source)) + 1
    env = os.environ.copy()
    for role in ("AUTHOR", "COMMITTER"):
        env[f"GIT_{role}_NAME"] = "Hepta qualification candidate"
        env[f"GIT_{role}_EMAIL"] = "qualification@example.invalid"
        env[f"GIT_{role}_DATE"] = f"{epoch} +0000"
    message = f"memory.retrieval qualification merge\n\nbase={base}\nsource={source}\n"
    args = ("-c", "commit.gpgsign=false", "commit-tree", tree, "-p", base, "-p", source)
    candidate = git(*args, input=message, env=env)
    if git(*args, input=message, env=env) != candidate:
        raise ValueError("synthetic merge identity is not deterministic")
    if git("show", "-s", "--format=%P", candidate) != f"{base} {source}":
        raise ValueError("synthetic merge parent order changed")
    return candidate, tree


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--base", required=True)
    parser.add_argument("--source", required=True)
    args = parser.parse_args()
    try:
        candidate, tree = synthetic_merge(args.root, args.base, args.source)
        print(f"candidate={candidate}\ntree={tree}")
        return 0
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"FAIL: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
