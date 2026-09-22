#!/usr/bin/env python3
"""Check the real Cargo manifest graph before downloading or compiling dependencies.

This is a read-only structural preflight, not compilation or dependency resolution.
Walk workspace members and their local dependencies, not unrelated fixture trees.
Check version/direction collisions in conventional SQLx migration directories
without running SQL or rewriting already-applied migration history.
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
import re
import sys
import tomllib


EXECUTION_BOUNDARIES = frozenset({"codex-core", "codex-extension-api"})
# Shared immutable provider/authority contracts already serve the execution spine.
# This is not a traversal exemption: their implementation dependencies are checked.
SHARED_KERNEL_CONTRACTS = frozenset({"codex-hepta-contracts"})
PRODUCT_PREFIXES = ("codex-hepta-", "hepta-", "codex-heptabao")


def execution_boundary_errors(
    package_paths: dict[Path, str],
    edges: dict[Path, list[tuple[str, Path | None, str]]],
) -> list[str]:
    """Report shortest local product paths, without following test-only edges.

    Paths, not package aliases, identify vertices. Each boundary is traversed
    once, so cycles and shared helpers cannot cause unbounded recursion.
    """
    errors = []
    # A reachable package can belong to another workspace and legitimately
    # reuse a name/version family. Check every manifest instance, not just the
    # first package with that name. Duplicate names within one owner workspace
    # are still rejected separately by verify_workspace.
    boundaries = sorted(
        ((path, name) for path, name in package_paths.items() if name in EXECUTION_BOUNDARIES),
        key=lambda item: (item[1], str(item[0])),
    )
    for root, name in boundaries:
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
    inherited = settings.get("dependencies", {})
    # Cargo rejects optional workspace definitions even when no member happens
    # to inherit them. Optionality belongs to the individual consumer.
    for dependency, declaration in inherited.items():
        if isinstance(declaration, dict) and declaration.get("optional") is True:
            errors.append(
                f"{workspace}: workspace.dependencies.{dependency} cannot be optional"
            )

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
    package_paths: dict[Path, str] = {}
    owned_names: dict[tuple[Path, str], Path] = {}
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
        package = manifest.get("package", {})
        name = package.get("name")
        if not isinstance(name, str) or not name:
            errors.append(f"{path}: package name missing")
        elif (owner, name) in owned_names and owned_names[owner, name] != path:
            errors.append(
                f"duplicate local package {name}: {owned_names[owner, name]} and {path}"
            )
        else:
            owned_names[owner, name] = path
            package_paths[path] = name
        for key, value in package.items():
            if isinstance(value, dict) and value.get("workspace") is True:
                if key not in package_settings.get("package", {}):
                    errors.append(f"{path}: workspace.package.{key} is missing")
        lints = manifest.get("lints", {})
        if isinstance(lints, dict) and lints.get("workspace") is True:
            if not isinstance(package_settings.get("lints"), dict):
                errors.append(f"{path}: workspace.lints is missing")
            if set(lints) - {"workspace"}:
                errors.append(f"{path}: cannot override workspace.lints in member lints")
        edition = package.get("edition", "2015")
        if isinstance(edition, dict) and edition.get("workspace") is True:
            edition = package_settings.get("package", {}).get("edition")
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
                        # This is a hard manifest error in edition 2024, but a
                        # warning in older editions. Do not invent a stricter
                        # policy or silently change the consumer's feature set.
                        # See the Rust edition guide's inherited-default-features.
                        if (
                            edition == "2024"
                            and declaration.get("default-features") is False
                            and not (
                                isinstance(workspace_declaration, dict)
                                and workspace_declaration.get("default-features") is False
                            )
                        ):
                            errors.append(
                                f"{path}: inherited dependency {dependency} disables "
                                "default-features in edition 2024, but "
                                f"workspace.dependencies.{dependency} does not disable them"
                            )
                        declaration = workspace_declaration
                        origin = owner
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
        # SQLx keys applied migrations by numeric version, not by filename.
        # Independently added migrations can therefore collide after a clean
        # text merge while cargo metadata still succeeds. Check only the direct
        # conventional directory of reachable SQLx packages, never fixture trees
        # or unrelated migration frameworks. Custom paths still need native CI.
        if any(target_name == "sqlx" for target_name, _, _ in edges.get(path, [])):
            migration_versions: dict[tuple[int, str], str] = {}
            for migration in sorted((path.parent / "migrations").glob("*.sql")):
                if not migration.is_file():
                    continue
                prefix, separator, _ = migration.name.partition("_")
                if not separator or re.fullmatch(r"[+-]?[0-9]+", prefix) is None:
                    continue
                version = int(prefix)
                if not 0 < version <= 2**63 - 1:
                    errors.append(f"{migration}: SQLx migration version must be a positive i64")
                    continue
                direction = "down" if migration.name.endswith(".down.sql") else "up"
                key = (version, direction)
                previous = migration_versions.get(key)
                if previous is not None:
                    errors.append(
                        f"{path}: SQLx migration version {version} ({direction}) collides: "
                        f"{previous} and {migration.name}; reconcile owner migration histories"
                    )
                else:
                    migration_versions[key] = migration.name
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
