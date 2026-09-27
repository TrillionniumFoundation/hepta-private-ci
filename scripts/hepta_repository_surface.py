#!/usr/bin/env python3
"""Freeze workflow/registry proliferation on ordinary repository changes."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_ROOT_REGISTRIES = {
    "docs/modules/MODULES.json",
    "docs/modules/SOURCE_BINDINGS.json",
    "docs/modules/MODULE_DOCS.json",
    "docs/modules/CI_MATRIX.json",
    "docs/modules/COMPILE_GRAPH.json",
    "docs/modules/registry.toml",
}


def added(base, head):
    return subprocess.check_output(
        [
            "git",
            "diff",
            "--diff-filter=A",
            "--name-only",
            base,
            head,
            "--",
        ],
        cwd=ROOT,
        text=True,
    ).splitlines()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    args = parser.parse_args()
    added_paths = added(args.base, args.head)
    forbidden = []
    for value in added_paths:
        path = PurePosixPath(value)
        if value.startswith(".github/workflows/"):
            forbidden.append(value)
        elif (
            path.parent == PurePosixPath("docs/modules")
            and value not in ALLOWED_ROOT_REGISTRIES
        ):
            forbidden.append(value)
        elif (
            len(path.parts) == 4
            and path.parts[:2] == ("docs", "modules")
            and path.name.endswith((".json", ".toml"))
            and path.name != "module.json"
        ):
            forbidden.append(value)
    if forbidden:
        raise SystemExit(
            "new workflow or registry infrastructure is frozen; use the "
            "shared CI tiers and module.json: "
            + ", ".join(sorted(forbidden))
        )
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_REPOSITORY_SURFACE",
                "added": len(added_paths),
            }
        )
    )


if __name__ == "__main__":
    main()
