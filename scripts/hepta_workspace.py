#!/usr/bin/env python3
"""Check the real Cargo manifest graph before downloading or compiling dependencies.

This is a read-only structural preflight, not compilation or dependency resolution.
Walk workspace members and their local dependencies, not unrelated fixture trees.
Reject Hepta product dependencies throughout the local normal/build dependency
closure of the execution core and extension API, including target-specific and
optional edges. Local patches are conservatively included without resolving
versions/features. Registry/git dependency internals still require Cargo and
native qualification; this is not a complete external dependency audit.
"""

from __future__ import annotations

import argparse
from collections import deque
from pathlib import Path
import sys
import tomllib


EXECUTION_BOUNDARIES = frozenset({"codex-core", "codex-extension-api"})
# Shared immutable provider/authority contracts already serve the execution spine.
# This is not a traversal exemption: their implementation dependencies are checked.
SHARED_KERNEL_CONTRACTS = frozenset({"codex-hepta-contracts"})
PRODUCT_PREFIXES = ("codex-hepta-", "hepta-", "codex-heptabao")


def execution_boundary_errors(
    package_paths: dict[str, Path],
    edges: dict[Path, list[tuple[str, Path | None, str]]],
) -> list[str]:
    """Report shortest local product paths, without following test-only edges.

    Paths, not package aliases, identify vertices. Each boundary is traversed
    once, so cycles and shared helpers cannot cause unbounded recursion.
    """
    errors = []
    for name in sorted(EXECUTION_BOUNDARIES & package_paths.keys()):
        root = package_paths[name]
        queue = deque([(root, name)])
        visited = {root}
        reported: set[str] = set()
        while queue:
            source, route = queue.popleft()
            for target_name, target, kind in sorted(
                edges.get(source, []), key=lambda edge: (edge[0], str(edge[1]), edge[2])
            ):
                if kind == "dev-dependencies":
                    continue
                next_route = f"{route} --{kind}--> {target_name}"
                if target_name.startswith(PRODUCT_PREFIXES) and target_name not in SHARED_KERNEL_CONTRACTS:
                    if target_name not in reported:
                        errors.append(
                            f"{root}: execution boundary: {next_route}; compose it in the host"
                        )
                        reported.add(target_name)
                elif target is not None and target not in visited:
                    visited.add(target)
                    queue.append((target, next_route))
    return errors


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
    # An external-looking dependency can be replaced by a local package. Follow
    # every local candidate: choosing versions would require a Cargo resolver.
    patches: dict[str, set[Path]] = {}
    for source in document.get("patch", {}).values():
        for alias, declaration in source.items():
            if not isinstance(declaration, dict) or "path" not in declaration:
                continue
            target_name = declaration.get("package", alias)
            if not isinstance(target_name, str):
                errors.append(f"workspace patch {alias}: invalid package name")
                continue
            target = (workspace / declaration["path"] / "Cargo.toml").resolve()
            patches.setdefault(target_name, set()).add(target)
            other = load(target)
            if other is not None and other.get("package", {}).get("name") != target_name:
                errors.append(f"workspace patch {alias}: {target} must name {target_name}")
            queue.append(target)
    edges: dict[Path, list[tuple[str, Path | None, str]]] = {}
    excluded = {
        path.resolve()
        for pattern in settings.get("exclude", [])
        for path in workspace.glob(pattern)
    }
    for pattern in settings.get("members", []):
        matches = sorted(workspace.glob(pattern))
        if not matches:
            errors.append(f"workspace member not found: {pattern}")
        queue.extend(
            path / "Cargo.toml" for path in matches if path.resolve() not in excluded
        )
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
            errors.append(
                f"duplicate local package {name}: {package_paths[name]} and {path}"
            )
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
                    origin = path.parent
                    if (
                        isinstance(declaration, dict)
                        and declaration.get("workspace") is True
                    ):
                        if dependency not in inherited:
                            errors.append(
                                f"{path}: workspace.dependencies.{dependency} is missing"
                            )
                            continue
                        declaration = inherited[dependency]
                        origin = workspace
                    target_name = (
                        declaration.get("package", dependency)
                        if isinstance(declaration, dict)
                        else dependency
                    )
                    if not isinstance(target_name, str):
                        errors.append(
                            f"{path}: {dependency} has an invalid package name"
                        )
                        continue
                    edges.setdefault(path, []).append((target_name, None, kind))
                    if not isinstance(declaration, dict) or "path" not in declaration:
                        for patched in sorted(patches.get(target_name, set())):
                            edges[path].append((target_name, patched, kind))
                        continue
                    target = (origin / declaration["path"] / "Cargo.toml").resolve()
                    other = load(target)
                    if other is None:
                        continue
                    actual = other.get("package", {}).get("name")
                    expected = declaration.get("package", dependency)
                    if actual != expected:
                        errors.append(
                            f"{path}: {dependency} expects {expected}, but {target} names {actual}"
                        )
                    edges[path].append((target_name, target, kind))
                    queue.append(target)
    errors.extend(execution_boundary_errors(package_paths, edges))
    return len(seen), sorted(set(errors))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "codex-rs",
    )
    arguments = parser.parse_args()
    try:
        count, errors = verify_workspace(arguments.workspace)
    except (TypeError, ValueError, KeyError) as error:
        print(f"invalid workspace manifest shape: {error}", file=sys.stderr)
        return 1
    for error in errors:
        print(error, file=sys.stderr)
    print(
        f"Cargo structural preflight: {count} local manifests; {len(errors)} errors; no code executed"
    )
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
