#!/usr/bin/env python3
"""Authoring helper: emit a map from committed Git objects; never push or qualify.

Commit source changes first, redirect stdout to a temporary file, review its diff,
then commit only the refreshed map. Qualification invokes the verifier, not this
helper. sourceBase is preserved; no execution/acceptance claim is promoted.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from cognitive_store_map_verify import MAP_PATH, ROOT, git, mapped_paths, object_at, require


def generate(root: Path, commit: str) -> dict:
    head = git(root, "rev-parse", "HEAD")
    require(commit == head, "bind only the checked-out authored source commit")
    require(not git(root, "status", "--porcelain", "--untracked-files=normal"),
            "commit source and metadata definitions before generating bindings")
    row = json.loads(git(root, "show", f"{commit}:{MAP_PATH}"))
    row["sourceObjects"] = [
        {"path": path, "object": object_at(root, commit, path)}
        for path in sorted(mapped_paths(row))
    ]
    row["sourceBindingSnapshot"] = {
        "commit": commit, "tree": git(root, "rev-parse", f"{commit}^{{tree}}"),
    }
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    print(json.dumps(generate(ROOT, args.source_commit), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
