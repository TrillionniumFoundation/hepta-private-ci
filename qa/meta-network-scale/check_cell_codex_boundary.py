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



def check_pure_cell_contract(root: Path) -> list[str]:
    """Ensure source Cell contracts remain independent of Codex and effects.

    This is only a closed-world direct-source and manifest check, not binary
    transitive attestation or a runtime FinalUse grant.
    """
    import re
    errors: list[str] = []
    manifest_path = root / "codex-rs" / "hepta-types" / "Cargo.toml"
    workspace_path = root / "codex-rs" / "Cargo.toml"
    try:
        manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
        workspace = tomllib.loads(workspace_path.read_text(encoding="utf-8"))
        root_deps = workspace["workspace"]["dependencies"]
        if manifest.get("package", {}).get("name") != "codex-hepta-types":
            errors.append("hepta-types: crate identity changed")
        inherited = root_deps.get("sha2")
        if inherited is None or (isinstance(inherited, dict) and inherited.get("package", "sha2") != "sha2"):
            errors.append("hepta-types: sha2 root dependency is absent or renamed")
    except (OSError, UnicodeError, tomllib.TOMLDecodeError, KeyError, TypeError, ValueError) as exc:
        return [f"hepta-types: cannot validate pure manifest: {exc}"]

    def visit(value: Any, scope: tuple[str, ...]) -> None:
        if not isinstance(value, dict):
            return
        for name, child in value.items():
            if name in DEPENDENCY_SECTIONS and isinstance(child, dict):
                for alias, item in child.items():
                    package = item.get("package", alias) if isinstance(item, dict) else alias
                    # Strictly permit only the existing hash primitive; no
                    # direct or renamed Codex, runtime, network or writer deps.
                    if alias != "sha2" or package != "sha2":
                        errors.append(
                            f"hepta-types: {'.'.join((*scope, name))}.{alias} "
                            f"introduces non-pure dependency {package}"
                        )
            if isinstance(child, dict):
                visit(child, (*scope, name))

    visit(manifest, ())
    pure = root / "codex-rs" / "hepta-types" / "src" / "execution_contract.rs"
    facade = root / "codex-rs" / "hepta-codex-adapter" / "src" / "execution_contract.rs"
    try:
        pure_source = pure.read_text(encoding="utf-8")
        facade_source = facade.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return errors + [f"hepta-types: missing source/facade: {exc}"]
    if re.search(r"\bcodex_[a-z0-9_]+::|\bextern\s+crate\s+codex_", pure_source):
        errors.append("hepta-types: pure execution contract imports a Codex crate")
    if "pub trait NativeExecutionAdapter" not in pure_source:
        errors.append("hepta-types: native execution contract missing")
    if "pub use codex_hepta_types::" not in facade_source:
        errors.append("hepta-codex-adapter: compatibility facade missing")
    # Prevent a second, independently mutable execution/receipt shape in
    # the Codex facade, which could bypass pure contract validation.
    if re.search(r"\b(?:pub\s+)?(?:struct|enum|trait)\s+(?:CellExecutionIntentV1|ExecutionReceiptV1|RuntimeReceiptV1)\b", facade_source):
        errors.append("hepta-codex-adapter: duplicate execution contract definition")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    args = parser.parse_args(argv)
    violations = check_workspace(args.root)
    violations.extend(check_pure_cell_contract(args.root))
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
