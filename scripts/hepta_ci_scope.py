#!/usr/bin/env python3
"""Select architecture checks by changed boundary, not a global prose gate.

This is scheduling only: it cannot grant merge, activation, or release. Unknown
source and shared contracts conservatively select every native group. Deleted
and renamed paths retain both owners through a --no-renames NUL-delimited diff.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path, PurePosixPath
from typing import Iterable

GROUPS = frozenset({"inference", "effects", "lifecycle", "learning", "objective"})
PACKAGE_GROUPS = {
    "hepta-infer-core": {"inference"},
    "hepta-operations": {"effects", "lifecycle"},
    "hepta-automation": {"effects", "lifecycle"},
    "hepta-control-plane": {"lifecycle", "effects"},
    "hepta-supervisor": {"lifecycle", "effects"},
    "hepta-fleet": {"lifecycle", "effects"},
    "hepta-learning-ledger": {"learning"},
    "hepta-learning-artifacts": {"learning"},
    "hepta-intelligence-eval": {"learning"},
    "hepta-objective": {"objective", "learning"},
    "hepta-prompt-optimizer": {"objective", "learning"},
}


def select(paths: Iterable[str], *, force_full: bool = False) -> dict[str, bool]:
    selected = set(GROUPS) if force_full else set()
    derived = force_full
    for path in paths:
        parts = PurePosixPath(path).parts
        if not path or path.startswith("/") or ".." in parts or "\\" in path or "\x00" in path:
            raise ValueError(f"invalid repository path: {path!r}")
        # Only established prose roots are exempt; a .md elsewhere may be an
        # include_str! input and therefore defaults to the conservative path.
        if path in {"README.md", "CONTRIBUTING.md"} or (path.startswith("docs/") and path.endswith(".md")):
            continue
        if path.startswith("docs/"):
            derived = True
            selected.update(GROUPS)
        elif path.startswith("apps/hepta-browser/"):
            selected.add("effects")
        elif len(parts) > 2 and parts[0] == "codex-rs" and parts[1] in PACKAGE_GROUPS:
            selected.update(PACKAGE_GROUPS[parts[1]])
        else:
            # Shared code, manifests, protocols, verifiers and workflow changes
            # must never be silently classified as documentation-only.
            selected.update(GROUPS)
            derived = True
    return {**{group: group in selected for group in sorted(GROUPS)}, "native": bool(selected), "derived": derived}


def changed_paths(base: str, head: str) -> list[str]:
    if not all(re.fullmatch(r"[0-9a-f]{40}", value) for value in (base, head)):
        raise ValueError("base and head must be exact 40-character Git commit identities")
    result = subprocess.run(
        ["git", "--no-replace-objects", "diff", "--no-ext-diff", "--no-textconv", "--name-only", "--no-renames", "-z", base, head, "--"],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return [value.decode("utf-8", "strict") for value in result.stdout.split(b"\0") if value]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base")
    parser.add_argument("--head", required=True)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.head):
        parser.error("--head must be an exact 40-character Git commit identity")
    if not args.full and not args.base:
        parser.error("an exact --base is required unless --full is explicitly selected")
    paths = [] if args.full else changed_paths(args.base, args.head)
    scope = select(paths, force_full=args.full)
    print(json.dumps({"source_head": args.head, "base": args.base, "paths": paths, "scope": scope}, sort_keys=True))
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as stream:
            for name, enabled in scope.items():
                stream.write(f"{name}={str(enabled).lower()}\n")


if __name__ == "__main__":
    main()
