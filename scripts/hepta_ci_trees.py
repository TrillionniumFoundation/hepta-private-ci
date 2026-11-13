#!/usr/bin/env python3
"""Prepare the exact two source trees consumed by the blocking CI scope gate.

The scope and dependency selectors use a two-tree diff, not a merge-base diff.
One shallow fetch of the exact comparison base is sufficient; fetching unrelated
branches, tags or full ancestry adds no input to that decision.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path


def git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(
        ["git", "--no-replace-objects", "-C", str(root), *args],
        stderr=subprocess.PIPE,
    )


def prepare_trees(root: Path, base: str, head: str) -> dict[str, str | bool]:
    for value in (base, head):
        if not re.fullmatch(r"[0-9a-f]{40}", value) or value == "0" * 40:
            raise ValueError(
                "base and head must be exact nonzero Git commit identities"
            )
    checked_out = git(root, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()
    if checked_out != head:
        raise ValueError("checkout differs from the exact candidate")
    try:
        available = git(root, "cat-file", "-t", base).strip() == b"commit"
    except subprocess.CalledProcessError:
        available = False
    if not available:
        # No ref wildcard, pruning, tag discovery, ancestry walk or API file cap.
        # Keep checkout's non-persisted credentials policy; public origin access
        # is sufficient for this repository. Any fetch failure remains a failure.
        git(
            root,
            "-c",
            "protocol.version=2",
            "fetch",
            "--no-tags",
            "--no-recurse-submodules",
            "--depth=1",
            "origin",
            base,
        )
    if git(root, "rev-parse", "--verify", base + "^{commit}").decode().strip() != base:
        raise ValueError("comparison base is not the exact requested commit")
    return {
        "source_head": head,
        "base": base,
        "head_tree": git(root, "rev-parse", "--verify", head + "^{tree}")
        .decode()
        .strip(),
        "base_tree": git(root, "rev-parse", "--verify", base + "^{tree}")
        .decode()
        .strip(),
        "base_fetched": not available,
        "comparison": "exact two-tree diff",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    args = parser.parse_args()
    print(json.dumps(prepare_trees(args.root, args.base, args.head), sort_keys=True))


if __name__ == "__main__":
    main()
