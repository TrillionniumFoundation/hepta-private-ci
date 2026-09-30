#!/usr/bin/env python3
"""Check/refresh artifact source objects without changing qualification claims.

For a prospective commit, stage changes first and pass --tree "$(git write-tree)".
This edits source metadata only with --write; it never runs during qualification
as an automatic repair and never changes sourceBase or acceptance state.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

from hepta_artifact_qualification import MAP, SOURCE_ROOT, strict_json


class BindingError(ValueError):
    pass


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def repository_path(path: object) -> str:
    if not isinstance(path, str) or not path or any(ord(char) < 32 for char in path):
        raise BindingError("invalid source path")
    parsed = PurePosixPath(path)
    if parsed.is_absolute() or ".." in parsed.parts or "\\" in path or str(parsed) != path:
        raise BindingError("source path must be canonical and repository-relative")
    if path == MAP:
        raise BindingError("implementation map cannot contain a self-referential blob seal")
    return path


def refreshed(root: Path, tree: str, mapping: dict, includes: list[str]) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", tree) or git(root, "cat-file", "-t", tree) != "tree":
        raise BindingError("a full existing Git tree identity is required")
    if not isinstance(mapping, dict) or mapping.get("module") != "learning.artifacts":
        raise BindingError("unexpected implementation map")
    result = copy.deepcopy(mapping)
    paths = set()
    for entry in result["sourceObjects"]:
        path = repository_path(entry["path"])
        if path in paths:
            raise BindingError("duplicate source object")
        paths.add(path)
    paths.add(SOURCE_ROOT)
    names = set()
    for operation in result["operations"]:
        name = operation["operation"]
        if not isinstance(name, str) or not name or name in names:
            raise BindingError("invalid or duplicate operation")
        names.add(name)
        paths.add(repository_path(operation["sourcePath"]))
    paths.update(repository_path(path) for path in includes)
    objects = {}
    for path in sorted(paths):
        value = git(root, "rev-parse", f"{tree}:{path}")
        if not re.fullmatch(r"[0-9a-f]{40}", value):
            raise BindingError("invalid source object identity")
        kind = git(root, "cat-file", "-t", value)
        if kind not in ("blob", "tree") or (path == SOURCE_ROOT and kind != "tree"):
            raise BindingError("invalid source object kind")
        objects[path] = value
    for operation in result["operations"]:
        path = operation["sourcePath"]
        if git(root, "cat-file", "-t", objects[path]) != "blob":
            raise BindingError("operation must bind a source file, not a directory")
        operation["sourceBlob"] = objects[path]
    result["sourceObjects"] = [{"path": path, "object": value} for path, value in objects.items()]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tree", help="full staged tree; defaults to HEAD^{tree}")
    parser.add_argument("--include", action="append", default=[], help="additional source input")
    parser.add_argument("--write", action="store_true", help="explicitly refresh metadata")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        tree = args.tree or git(root, "rev-parse", "HEAD^{tree}")
        path = root / MAP
        mapping = strict_json(path.read_bytes())
        result = refreshed(root, tree, mapping, args.include)
        if args.write:
            path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        elif result != mapping:
            raise BindingError("stale source objects; refresh explicitly before committing")
        print(json.dumps({"sourceObjectsCurrent": True, "claimsAdvanced": False, "tree": tree}))
        return 0
    except (ValueError, OSError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        print(json.dumps({"sourceObjectsCurrent": False, "error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
