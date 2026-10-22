#!/usr/bin/env python3
"""Reject direct Codex harness dependencies from Hepta cell/decision crates.

A source-only architectural gate; it does not grant runtime, model, tool or
promotion authority. Cell owners may depend on Hepta contracts and pure
utilities, but execution effects must enter through the typed adapter owner.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import tomllib
from typing import Any

CELL_CRATES = (
    "hepta-neuron",
    "hepta-intuition",
    "hepta-ndu",
    "hepta-plasticity",
    "hepta-infer-core",
    "hepta-cognitive-types",
    "hepta-types",
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


def normalized_package(name: str) -> str:
    return name.lower().replace("_", "-")


def prohibited_package(package: str) -> bool:
    package = normalized_package(package)
    return package.startswith("codex-") and package not in ALLOWED_PACKAGES


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
            elif isinstance(child, dict):
                visit(child, (*keys, key))

    visit(manifest, ())
    return violations


def check_foundation_manifest(manifest: dict[str, Any]) -> list[str]:
    """The authority-free Cell contract crate can depend only on pinned sha2.

    A non-Codex runtime such as tokio/rmcp/reqwest could bypass the normal
    codex-* denylist without this strict foundational dependency check.
    """
    violations: list[str] = []
    dependencies = manifest.get("dependencies")
    if dependencies != {"sha2": {"workspace": True}}:
        violations.append(
            "hepta-types: foundation dependencies must be exactly sha2 (workspace = true)"
        )
    for key in ("dev-dependencies", "build-dependencies"):
        if manifest.get(key):
            violations.append(f"hepta-types: unreviewed {key} dependencies")
    targets = manifest.get("target")
    if isinstance(targets, dict):
        for target, configuration in targets.items():
            if isinstance(configuration, dict):
                for key in DEPENDENCY_SECTIONS:
                    if configuration.get(key):
                        violations.append(
                            f"hepta-types: target.{target}.{key} may not add dependencies"
                        )
    return violations


def check_foundation_build_boundary(manifest: dict[str, Any], crate_root: Path) -> list[str]:
    """Deny compile-time effects even without extra Cargo dependencies.

    Cargo automatically executes an adjacent build.rs unless explicitly disabled.
    An imported contract crate cannot become an authority path by adding a build
    script, proc macro or custom native linking declaration.
    """
    violations: list[str] = []
    package = manifest.get("package")
    package = package if isinstance(package, dict) else {}
    if "build" in package and package["build"] is not False:
        violations.append("hepta-types: explicit build script is forbidden")
    if "links" in package:
        violations.append("hepta-types: native linking declaration is forbidden")

    lib = manifest.get("lib")
    lib = lib if isinstance(lib, dict) else {}
    if lib.get("proc-macro") is True:
        violations.append("hepta-types: proc-macro entry point is forbidden")

    implicit_build = crate_root / "build.rs"
    if implicit_build.is_symlink() or implicit_build.exists():
        violations.append("hepta-types: implicit build.rs is forbidden")
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
        if name == "hepta-types":
            violations.extend(check_foundation_manifest(manifest))
            violations.extend(check_foundation_build_boundary(manifest, manifest_file.parent))
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
