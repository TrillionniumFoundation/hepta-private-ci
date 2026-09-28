#!/usr/bin/env python3
"""Freeze workflow and registry proliferation on ordinary repository changes."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from pathlib import PurePosixPath
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_ROOT_MODULE_FILES = {
    "docs/modules/CI_MATRIX.json",
    "docs/modules/COMPILE_GRAPH.json",
    "docs/modules/registry.toml",
}


def added_paths(base: str, head: str, root: Path = ROOT) -> list[str]:
    return subprocess.check_output(
        [
            "git",
            "--no-replace-objects",
            "diff",
            "--diff-filter=A",
            "--name-only",
            "--no-renames",
            base,
            head,
            "--",
            ".github/workflows",
            "docs/modules",
        ],
        cwd=root,
        text=True,
    ).splitlines()


def forbidden_additions(paths: Iterable[str]) -> list[str]:
    forbidden: list[str] = []
    for value in paths:
        path = PurePosixPath(value)
        if value.startswith(".github/workflows/"):
            forbidden.append(value)
        elif path.parent == PurePosixPath("docs/modules"):
            if value not in ALLOWED_ROOT_MODULE_FILES:
                forbidden.append(value)
        elif (
            len(path.parts) == 4
            and path.parts[:2] == ("docs", "modules")
            and path.name.endswith((".json", ".toml"))
            and path.name != "module.toml"
        ):
            forbidden.append(value)
    return sorted(forbidden)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    args = parser.parse_args()
    added = added_paths(args.base, args.head)
    forbidden = forbidden_additions(added)
    if forbidden:
        raise SystemExit(
            "new workflow or registry infrastructure is frozen; use the shared "
            "CI tiers and one module.toml: " + ", ".join(forbidden)
        )
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_REPOSITORY_SURFACE",
                "added": len(added),
                "forbidden": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
