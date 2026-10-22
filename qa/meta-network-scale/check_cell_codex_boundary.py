#!/usr/bin/env python3
"""Reject direct Codex harness dependencies from Hepta cell/decision crates.

A source-only architectural gate; it does not grant runtime, model, tool or
promotion authority. Cell owners may depend on Hepta contracts and pure
utilities, but execution effects must enter through the typed adapter owner.
"""
from __future__ import annotations

import argparse
import posixpath
from pathlib import Path
import sys
import tomllib
from typing import Any

CELL_CRATES = (
    "hepta-types",
    "hepta-neuron",
    "hepta-intuition",
    "hepta-ndu",
    "hepta-plasticity",
    "hepta-infer-core",
    "hepta-cognitive-types",
)
DEPENDENCY_SECTIONS = frozenset(
    ("dependencies", "dev-dependencies", "build-dependencies")
)
# Admit only reviewed, authority-free Cell/Cognitive contract crates and pure
# paths. Broad codex-hepta-* or codex-utils-* allowances could accidentally
# admit agentd, tool/PTY, governance or production writer dependencies.
ALLOWED_PACKAGES = frozenset(
    (
        "codex-hepta-types",
        "codex-hepta-contracts",
        "codex-hepta-infer-core",
        "codex-hepta-ndu",
        "codex-hepta-intuition",
        "codex-hepta-plasticity",
        "codex-hepta-cognitive-types",
        "codex-utils-absolute-path",
    )
)

# A new dependency must be explicitly reviewed rather than silently acquiring
# an execution client, native host tools, network transport or dynamic loader.
# These external crates are already in the verified Cell crate manifests.
ALLOWED_EXTERNAL_PACKAGES = frozenset(
    (
        "sha2",
        "serde",
        "serde-json",
        "pretty-assertions",
        "ed25519-dalek",
        "tempfile",
    )
)


def normalized_package(name: str) -> str:
    return name.lower().replace("_", "-")


def prohibited_package(package: str) -> bool:
    package = normalized_package(package)
    return package.startswith("codex-") and package not in ALLOWED_PACKAGES



# These are exact checked-in source directories, not merely permitted Cargo
# package names. A crate could otherwise impersonate an approved dependency
# via git, an alternate registry, or a path outside this workspace.
LOCAL_PACKAGE_DIRECTORIES = {
    "codex-hepta-types": "hepta-types",
    "codex-hepta-contracts": "hepta-contracts",
    "codex-hepta-infer-core": "hepta-infer-core",
    "codex-hepta-ndu": "hepta-ndu",
    "codex-hepta-intuition": "hepta-intuition",
    "codex-hepta-plasticity": "hepta-plasticity",
    "codex-hepta-cognitive-types": "hepta-cognitive-types",
    "codex-utils-absolute-path": "utils/absolute-path",
}
SOURCE_OVERRIDE_KEYS = frozenset(("git", "registry", "branch", "tag", "rev"))


def dependency_origin_violation(
    alias: str,
    declaration: Any,
    package: str,
    crate: str,
    workspace_dependencies: dict[str, Any] | None,
) -> str | None:
    """Pin approved package *origins* as well as package names.

    This is lexical Cargo source-custody validation, not a substitute for
    Cargo.lock verification, a complete transitive graph, or an OS sandbox.
    The production caller always supplies the root workspace dependencies.
    """
    normalized = normalized_package(package)
    if (
        normalized not in LOCAL_PACKAGE_DIRECTORIES
        and normalized not in ALLOWED_EXTERNAL_PACKAGES
    ):
        return None

    source = declaration
    inherited = isinstance(declaration, dict) and declaration.get("workspace") is True
    if inherited:
        if workspace_dependencies is None:
            # Standalone unit-callers may lack the root manifest. The actual
            # check_workspace CLI always supplies it.
            return None
        source = workspace_dependencies.get(alias)
        if source is None:
            return "missing inherited workspace source"
        if any(key in declaration for key in (*SOURCE_OVERRIDE_KEYS, "path")):
            return "workspace member overrides inherited dependency source"
        root_package = (
            source.get("package", alias) if isinstance(source, dict) else alias
        )
        member_package = declaration.get("package", root_package)
        if (
            not isinstance(root_package, str)
            or not isinstance(member_package, str)
            or normalized_package(root_package) != normalized_package(member_package)
        ):
            return "workspace dependency package identity differs from member"

    if normalized in LOCAL_PACKAGE_DIRECTORIES:
        if not isinstance(source, dict):
            return "approved local package lacks a pinned local path"
        if any(key in source for key in (*SOURCE_OVERRIDE_KEYS, "version")):
            return "approved local package has a non-local or mixed source"
        relative = source.get("path")
        if (
            not isinstance(relative, str)
            or not relative
            or posixpath.isabs(relative)
        ):
            return "approved local package lacks a relative source path"
        # Workspace-root paths resolve relative to codex-rs/. Direct member
        # paths resolve relative to codex-rs/<crate>/.
        resolved = posixpath.normpath(
            posixpath.join("" if inherited else crate, relative)
        )
        if resolved != LOCAL_PACKAGE_DIRECTORIES[normalized]:
            return (
                f"approved local package resolves to {resolved!r}, expected "
                f"{LOCAL_PACKAGE_DIRECTORIES[normalized]!r}"
            )
    elif isinstance(source, dict):
        if any(key in source for key in (*SOURCE_OVERRIDE_KEYS, "path")):
            return "approved external package uses an unreviewed source"
    elif not isinstance(source, str):
        return "approved external package has an invalid source declaration"
    return None


def check_manifest(
    manifest: dict[str, Any], crate: str, workspace_dependencies: dict[str, Any] | None = None
) -> list[str]:
    """Inspect every Cargo dependency table, including target-specific tables.

    Resolve package renaming, so an innocuous dependency alias cannot silently
    bring codex-core back into a cell's compile-time type graph.
    """
    violations: list[str] = []

    def visit(value: Any, keys: tuple[str, ...]) -> None:
        if not isinstance(value, dict):
            return
        for key, child in value.items():
            if key in DEPENDENCY_SECTIONS and isinstance(child, dict):
                for alias, declaration in child.items():
                    package = (
                        declaration.get("package", alias)
                        if isinstance(declaration, dict)
                        else alias
                    )
                    if isinstance(package, str) and prohibited_package(package):
                        location = ".".join((*keys, key))
                        violations.append(
                            f"{crate}: {location}.{alias} directly depends on "
                            f"the Codex execution crate {package}"
                        )
                        continue
                    # Cargo workspace = true inherits the root declaration,
                    # including its real package name. A harmless-looking local
                    # alias can otherwise point directly at codex-core.
                    if isinstance(declaration, dict) and declaration.get("workspace") is True:
                        if workspace_dependencies is not None:
                            inherited = workspace_dependencies.get(alias)
                            if inherited is None:
                                violations.append(
                                    f"{crate}: {key}.{alias} has no root workspace dependency"
                                )
                                continue
                            package = (
                                inherited.get("package", alias)
                                if isinstance(inherited, dict)
                                else alias
                            )
                    if isinstance(package, str) and prohibited_package(package):
                        location = ".".join((*keys, key))
                        violations.append(
                            f"{crate}: {location}.{alias} directly depends on "
                            f"the Codex execution crate {package}"
                        )
                    elif isinstance(package, str):
                        normalized = normalized_package(package)
                        location = ".".join((*keys, key))
                        origin_error = dependency_origin_violation(
                            alias, declaration, package, crate, workspace_dependencies
                        )
                        if origin_error is not None:
                            violations.append(
                                f"{crate}: {location}.{alias} source custody: {origin_error}"
                            )
                        if crate == "hepta-types" and normalized != "sha2":
                            violations.append(
                                f"{crate}: {location}.{alias} is not an approved "
                                f"foundational dependency ({package})"
                            )
                        elif (
                            crate != "hepta-types"
                            and normalized not in ALLOWED_PACKAGES
                            and normalized not in ALLOWED_EXTERNAL_PACKAGES
                        ):
                            violations.append(
                                f"{crate}: {location}.{alias} is not an approved "
                                f"Cell dependency ({package})"
                            )
            elif isinstance(child, dict):
                visit(child, (*keys, key))

    visit(manifest, ())
    return violations


def check_workspace(root: Path) -> list[str]:
    violations: list[str] = []
    workspace_file = root / "codex-rs" / "Cargo.toml"
    try:
        workspace = tomllib.loads(workspace_file.read_text(encoding="utf-8"))
        workspace_deps = workspace["workspace"]["dependencies"]
        if not isinstance(workspace_deps, dict):
            raise ValueError("workspace.dependencies must be a table")
    except (OSError, UnicodeError, tomllib.TOMLDecodeError, KeyError, TypeError, ValueError) as exc:
        return [f"workspace: cannot resolve dependency inheritance: {exc}"]
    for name in CELL_CRATES:
        manifest_file = root / "codex-rs" / name / "Cargo.toml"
        try:
            manifest = tomllib.loads(manifest_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
            violations.append(f"{name}: cannot parse pinned Cargo manifest: {exc}")
            continue
        package_info = manifest.get("package")
        package_name = package_info.get("name") if isinstance(package_info, dict) else None
        if package_name != f"codex-{name}":
            violations.append(f"{name}: crate identity differs from expected codex-{name}")
        violations.extend(check_manifest(manifest, name, workspace_deps))
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    args = parser.parse_args(argv)
    violations = check_workspace(args.root)
    for violation in violations:
        print(violation, file=sys.stderr)
    if violations:
        return 1
    print(
        f"Cell/Codex crate isolation: {len(CELL_CRATES)} owners checked; "
        "no direct harness dependencies"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
