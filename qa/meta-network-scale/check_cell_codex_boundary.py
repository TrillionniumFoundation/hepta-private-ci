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
)
DEPENDENCY_SECTIONS = frozenset(
    ("dependencies", "dev-dependencies", "build-dependencies")
)
# Codex core, app-server, session, tools, SDK and protocol crates belong to the
# shared execution spine. Standalone Hepta contracts and Codex pure utilities
# are permitted: this gate prevents direct coupling, not all transitive use.
ALLOWED_PREFIXES = ("codex-hepta-", "codex-utils-")


def normalized_package(name: str) -> str:
    return name.lower().replace("_", "-")


def prohibited_package(package: str) -> bool:
    package = normalized_package(package)
    return package.startswith("codex-") and not package.startswith(ALLOWED_PREFIXES)


def check_manifest(manifest: dict[str, Any], crate: str) -> list[str]:
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
            elif isinstance(child, dict):
                visit(child, (*keys, key))

    visit(manifest, ())
    return violations


def check_workspace(root: Path) -> list[str]:
    violations: list[str] = []
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
        violations.extend(check_manifest(manifest, name))
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
