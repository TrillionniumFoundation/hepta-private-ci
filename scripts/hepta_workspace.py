#!/usr/bin/env python3
"""Check the real Cargo manifest graph before downloading or compiling dependencies.

This is a read-only structural preflight, not compilation or dependency resolution.
Walk workspace members and their local dependencies, not unrelated fixture trees.
"""
from __future__ import annotations

import argparse
from collections import deque
from pathlib import Path
import sys
import tomllib


def verify_workspace(workspace: Path) -> tuple[int, list[str]]:
    workspace = workspace.resolve()
    errors: list[str] = []
    manifests: dict[Path, dict] = {}

    def load(path: Path) -> dict | None:
        path = path.resolve()
        if path in manifests:
            return manifests[path]
        try:
            value = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
            errors.append(f"{path}: {error}")
            return None
        manifests[path] = value
        return value

    document = load(workspace / "Cargo.toml")
    if document is None:
        return 0, errors
    settings = document.get("workspace")
    if not isinstance(settings, dict):
        return 0, [f"{workspace}: missing [workspace]"]
    inherited = settings.get("dependencies", {})
    queue: deque[Path] = deque()
    excluded = {
        path.resolve()
        for pattern in settings.get("exclude", [])
        for path in workspace.glob(pattern)
    }
    for pattern in settings.get("members", []):
        matches = sorted(workspace.glob(pattern))
        if not matches:
            errors.append(f"workspace member not found: {pattern}")
        queue.extend(path / "Cargo.toml" for path in matches if path.resolve() not in excluded)
    if "package" in document:
        queue.append(workspace / "Cargo.toml")
    seen: set[Path] = set()
    package_paths: dict[str, Path] = {}
    while queue:
        path = queue.popleft().resolve()
        if path in seen:
            continue
        seen.add(path)
        manifest = load(path)
        if manifest is None:
            continue
        package = manifest.get("package", {})
        name = package.get("name")
        if not isinstance(name, str) or not name:
            errors.append(f"{path}: package name missing")
        elif name in package_paths and package_paths[name] != path:
            errors.append(f"duplicate local package {name}: {package_paths[name]} and {path}")
        else:
            package_paths[name] = path
        for key, value in package.items():
            if isinstance(value, dict) and value.get("workspace") is True:
                if key not in settings.get("package", {}):
                    errors.append(f"{path}: workspace.package.{key} is missing")
        groups = [manifest, *manifest.get("target", {}).values()]
        for group in groups:
            for kind in ("dependencies", "dev-dependencies", "build-dependencies"):
                for dependency, declaration in group.get(kind, {}).items():
                    if not isinstance(declaration, dict):
                        continue
                    origin = path.parent
                    if declaration.get("workspace") is True:
                        if dependency not in inherited:
                            errors.append(f"{path}: workspace.dependencies.{dependency} is missing")
                            continue
                        declaration = inherited[dependency]
                        origin = workspace
                    if not isinstance(declaration, dict) or "path" not in declaration:
                        continue
                    target = (origin / declaration["path"] / "Cargo.toml").resolve()
                    other = load(target)
                    if other is None:
                        continue
                    actual = other.get("package", {}).get("name")
                    expected = declaration.get("package", dependency)
                    if actual != expected:
                        errors.append(f"{path}: {dependency} expects {expected}, but {target} names {actual}")
                    queue.append(target)
    return len(seen), sorted(set(errors))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path(__file__).resolve().parents[1] / "codex-rs")
    arguments = parser.parse_args()
    try:
        count, errors = verify_workspace(arguments.workspace)
    except (TypeError, ValueError, KeyError) as error:
        print(f"invalid workspace manifest shape: {error}", file=sys.stderr)
        return 1
    for error in errors:
        print(error, file=sys.stderr)
    print(f"Cargo structural preflight: {count} local manifests; {len(errors)} errors; no code executed")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
