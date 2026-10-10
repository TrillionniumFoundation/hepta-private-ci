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
import re
import tomllib


def verify_workspace(workspace: Path) -> tuple[int, list[str]]:
    workspace = workspace.resolve()
    errors: list[str] = []
    manifests: dict[Path, dict | None] = {}

    def load(path: Path) -> dict | None:
        path = path.resolve()
        if path in manifests:
            return manifests[path]
        try:
            value = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
            errors.append(f"{path}: {error}")
            manifests[path] = None
            return None
        manifests[path] = value
        return value

    document = load(workspace / "Cargo.toml")
    if document is None:
        return 0, errors
    settings = document.get("workspace")
    if not isinstance(settings, dict):
        return 0, [f"{workspace}: missing [workspace]"]

    def owner_settings(path: Path, manifest: dict) -> tuple[Path, dict]:
        # A reachable path dependency may own a different workspace. Never
        # validate its inherited fields against this repository's root by
        # accident. This only reads its explicit root or ancestor manifests.
        explicit = manifest.get("package", {}).get("workspace")
        if explicit is not None:
            if not isinstance(explicit, str):
                errors.append(f"{path}: package.workspace must be a path")
                return path.parent, {}
            owner = (path.parent / explicit).resolve()
            parent = load(owner / "Cargo.toml")
            if parent is None or not isinstance(parent.get("workspace"), dict):
                errors.append(f"{path}: package.workspace has no [workspace]")
                return owner, {}
            return owner, parent["workspace"]
        for directory in (path.parent, *path.parent.parents):
            candidate = directory / "Cargo.toml"
            if not candidate.is_file():
                continue
            parent = load(candidate)
            if parent is None:
                return directory, {}
            if isinstance(parent.get("workspace"), dict):
                options = parent["workspace"]
                excluded = {
                    item.resolve()
                    for pattern in options.get("exclude", [])
                    for item in directory.glob(pattern)
                }
                if path.parent != directory and path.parent in excluded:
                    return path.parent, {}
                return directory, options
        return path.parent, {}

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
        queue.extend(
            path / "Cargo.toml" for path in matches if path.resolve() not in excluded
        )
    if "package" in document:
        queue.append(workspace / "Cargo.toml")
    seen: set[Path] = set()
    package_paths: dict[tuple[Path, str], Path] = {}
    package_names: dict[Path, str] = {}
    runtime_edges: dict[Path, list[tuple[str, str, Path | None]]] = {}
    checked_owners: set[Path] = set()
    while queue:
        path = queue.popleft().resolve()
        if path in seen:
            continue
        seen.add(path)
        manifest = load(path)
        if manifest is None:
            continue
        owner, package_settings = owner_settings(path, manifest)
        inherited = package_settings.get("dependencies", {})
        if owner not in checked_owners:
            checked_owners.add(owner)
            for dependency, declaration in inherited.items():
                if (
                    isinstance(declaration, dict)
                    and declaration.get("optional") is True
                ):
                    errors.append(
                        f"{owner}: workspace.dependencies.{dependency} cannot be optional"
                    )
        root_document = load(owner / "Cargo.toml") or {}
        local_patches = {}
        for alias, declaration in (
            root_document.get("patch", {}).get("crates-io", {}).items()
        ):
            if isinstance(declaration, dict) and isinstance(
                declaration.get("path"), str
            ):
                local_patches[declaration.get("package", alias)] = declaration
        package = manifest.get("package", {})
        name = package.get("name")
        if not isinstance(name, str) or not name:
            errors.append(f"{path}: package name missing")
        elif (owner, name) in package_paths and package_paths[owner, name] != path:
            errors.append(
                f"duplicate local package {name}: {package_paths[owner, name]} and {path}"
            )
        else:
            package_paths[owner, name] = path
        if isinstance(name, str):
            package_names[path] = name
        runtime_edges[path] = []
        uses_sqlx = False
        edition = package.get("edition", "2015")
        if isinstance(edition, dict):
            edition = package_settings.get("package", {}).get("edition", "2015")
        for key, value in package.items():
            if isinstance(value, dict) and value.get("workspace") is True:
                if key not in package_settings.get("package", {}):
                    errors.append(f"{path}: workspace.package.{key} is missing")
        if manifest.get("lints", {}).get("workspace") is True:
            if set(manifest["lints"]) != {"workspace"}:
                errors.append(f"{path}: member cannot override workspace.lints")
            if not isinstance(package_settings.get("lints"), dict):
                errors.append(f"{path}: workspace.lints is missing")
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
                        workspace_declaration = inherited[dependency]
                        disabled = (
                            isinstance(workspace_declaration, dict)
                            and workspace_declaration.get("default-features") is False
                        )
                        if (
                            edition == "2024"
                            and declaration.get("default-features") is False
                            and not disabled
                        ):
                            errors.append(
                                f"{path}: default-features=false cannot disable workspace.dependencies.{dependency} defaults in edition 2024"
                            )
                        declaration = workspace_declaration
                        origin = owner
                    if isinstance(declaration, str):
                        declaration = {"version": declaration}
                    if not isinstance(declaration, dict):
                        errors.append(
                            f"{path}: invalid dependency declaration for {dependency}"
                        )
                        continue
                    expected = declaration.get("package", dependency)
                    if not isinstance(expected, str) or not expected:
                        errors.append(f"{path}: {dependency} has invalid package name")
                        continue
                    uses_sqlx |= expected == "sqlx"
                    patched = False
                    if (
                        "path" not in declaration
                        and "git" not in declaration
                        and "registry" not in declaration
                        and expected in local_patches
                    ):
                        declaration = local_patches[expected]
                        origin = owner
                        patched = True
                    target = None
                    if "path" in declaration:
                        if not isinstance(declaration["path"], str):
                            errors.append(
                                f"{path}: invalid local dependency path for {dependency}"
                            )
                            continue
                        target = (origin / declaration["path"] / "Cargo.toml").resolve()
                        other = load(target)
                        if other is not None:
                            actual = other.get("package", {}).get("name")
                            if actual != expected:
                                message = (
                                    f"patch {target} must name {expected}"
                                    if patched
                                    else f"{dependency} expects {expected}, but {target} names {actual}"
                                )
                                errors.append(f"{path}: {message}")
                            queue.append(target)
                    if kind != "dev-dependencies":
                        runtime_edges[path].append((kind, expected, target))
        if uses_sqlx:
            versions = {}
            for migration in sorted((path.parent / "migrations").glob("*.sql")):
                prefix = migration.name.split("_", 1)[0]
                if re.fullmatch(r"[+-]?[0-9]+", prefix) is None:
                    continue
                version = int(prefix)
                if not 0 < version < 2**63:
                    errors.append(
                        f"{migration}: SQLx migration version must be a positive i64"
                    )
                    continue
                direction = "down" if migration.name.endswith(".down.sql") else "up"
                key = (version, direction)
                if key in versions:
                    errors.append(
                        f"{path}: migration version {version} ({direction}) collides: {versions[key]} and {migration.name}"
                    )
                else:
                    versions[key] = migration.name
    # Trace actual package paths, not names: independent workspaces may carry
    # two versions of the same execution boundary. Test-only edges stay local.
    shared_contracts = {
        "codex-hepta-contracts",
        "codex-hepta-types",
        "codex-hepta-paths",
        "codex-hepta-wire",
    }
    for boundary in sorted(package_names):
        if package_names[boundary] not in {"codex-core", "codex-extension-api"}:
            continue
        pending = deque([(boundary, package_names[boundary])])
        visited = set()
        while pending:
            current, route = pending.popleft()
            if current in visited:
                continue
            visited.add(current)
            for kind, dependency, target in sorted(
                runtime_edges.get(current, []),
                key=lambda edge: (edge[0], edge[1], str(edge[2])),
            ):
                next_route = f"{route} --{kind}--> {dependency}"
                if (
                    dependency.startswith("codex-hepta")
                    and dependency not in shared_contracts
                ):
                    errors.append(
                        f"{boundary}: execution boundary reaches product implementation: {next_route}"
                    )
                elif target is not None:
                    pending.append((target, next_route))
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
