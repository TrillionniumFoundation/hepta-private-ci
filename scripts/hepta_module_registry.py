#!/usr/bin/env python3
"""Compare the canonical module registry with Hepta Cargo packages.

``docs/modules/MODULES.json`` is the source of module identity.  Cargo is the
source of compiled package identity, and ``CARGO_BINDINGS.json`` is the single
explicit package-to-module ownership registry.  This module deliberately does
not infer module IDs from package names: ownership must be declared in the
package registry or a module ``rootBindings[].path`` entry.
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "hepta.module-registry-drift.v1"
DEFAULT_MODULES = Path("docs/modules/MODULES.json")
DEFAULT_CARGO_BINDINGS = Path("docs/modules/CARGO_BINDINGS.json")
DEFAULT_CARGO_ROOT = Path("codex-rs")


@dataclass(frozen=True, order=True)
class CargoCrate:
    """A compiled Hepta package and its workspace-relative source root."""

    package: str
    path: str


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def load_module_registry(path: Path) -> list[dict[str, Any]]:
    """Load and minimally validate canonical module rows."""
    document = json.loads(path.read_text(encoding="utf-8"))
    modules = document.get("modules")
    if not isinstance(modules, list) or not modules:
        raise ValueError(f"{path}: modules must be a non-empty list")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in modules:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise ValueError(f"{path}: every module must have a string id")
        module_id = row["id"]
        if module_id in seen:
            raise ValueError(f"{path}: duplicate module id: {module_id}")
        seen.add(module_id)
        bindings = row.get("rootBindings", [])
        if not isinstance(bindings, list):
            raise ValueError(f"{path}: {module_id}.rootBindings must be a list")
        for binding in bindings:
            if not isinstance(binding, dict) or not isinstance(binding.get("path"), str):
                raise ValueError(f"{path}: {module_id} has an invalid root binding")
        rows.append(row)
    return rows


def discover_cargo_hepta_crates(root: Path, cargo_root: Path = DEFAULT_CARGO_ROOT) -> list[CargoCrate]:
    """Discover ``codex-hepta-*`` packages under the Rust workspace.

    Qualification fixtures and non-workspace Cargo projects are intentionally
    excluded by the default ``codex-rs`` root.  Pass a different root when a
    separate workspace needs auditing.
    """
    base = root / cargo_root
    if not base.is_dir():
        raise ValueError(f"Cargo root does not exist: {cargo_root}")
    crates: list[CargoCrate] = []
    for manifest in sorted(base.rglob("Cargo.toml")):
        try:
            document = tomllib.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as error:
            raise ValueError(f"cannot parse {manifest}: {error}") from error
        package = document.get("package", {}).get("name")
        if isinstance(package, str) and package.startswith("codex-hepta-"):
            crates.append(CargoCrate(package=package, path=_relative(manifest.parent, root)))
    return crates


def _declared_bindings(modules: Iterable[dict[str, Any]]) -> dict[str, list[str]]:
    owners: dict[str, list[str]] = {}
    for module in modules:
        for binding in module.get("rootBindings", []):
            path = binding["path"].rstrip("/")
            owners.setdefault(path, []).append(module["id"])
    return owners


def load_cargo_bindings(root: Path) -> dict[str, list[str]]:
    """Load the single explicit package-to-module ownership registry."""
    path = root / DEFAULT_CARGO_BINDINGS
    if not path.is_file():
        return {}
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema") != "hepta.cargo-module-binding.v1":
        raise ValueError(f"{path}: unsupported schema")
    bindings = document.get("bindings")
    if not isinstance(bindings, list):
        raise ValueError(f"{path}: bindings must be a list")
    owners: dict[str, list[str]] = {}
    for row in bindings:
        if not isinstance(row, dict) or not isinstance(row.get("packagePath"), str) or not isinstance(row.get("module"), str):
            raise ValueError(f"{path}: invalid package binding")
        owners.setdefault(row["packagePath"].rstrip("/"), []).append(row["module"])
    return owners


def compare_registry(
    root: Path,
    *,
    modules_path: Path = DEFAULT_MODULES,
    cargo_root: Path = DEFAULT_CARGO_ROOT,
) -> dict[str, Any]:
    """Return a deterministic, JSON-serialisable registry drift report."""
    modules = load_module_registry(root / modules_path)
    crates = discover_cargo_hepta_crates(root, cargo_root)
    module_owners = _declared_bindings(modules)
    cargo_owners = load_cargo_bindings(root)
    explicit_cargo_registry = (root / DEFAULT_CARGO_BINDINGS).is_file()
    owners = cargo_owners if explicit_cargo_registry else module_owners
    module_ids = {module["id"] for module in modules}
    crate_by_path = {crate.path: crate for crate in crates}

    bound: list[dict[str, str]] = []
    unclaimed: list[dict[str, str]] = []
    for crate in crates:
        binding_modules = owners.get(crate.path, [])
        if len(binding_modules) == 1:
            bound.append({"package": crate.package, "path": crate.path, "module": binding_modules[0]})
        elif not binding_modules:
            unclaimed.append(asdict(crate))

    ambiguous = [
        {"path": path, "modules": sorted(module_ids)}
        for path, module_ids in sorted(owners.items())
        if len(module_ids) > 1
    ]
    unknown_modules = sorted(
        {module_id for module_ids in owners.values() for module_id in module_ids}
        - module_ids
    )
    modules_without_package: list[dict[str, Any]] = []
    for module in modules:
        paths = [binding["path"].rstrip("/") for binding in module.get("rootBindings", [])]
        package_paths = [
            path
            for path, binding_modules in owners.items()
            if module["id"] in binding_modules and path in crate_by_path
        ]
        if not package_paths:
            modules_without_package.append({"module": module["id"], "paths": paths})

    # A missing package for a declared root is useful evidence, but not all
    # module roots are Rust crates (UI, external systems and tools are valid).
    declared_without_package = sorted(
        path for path in module_owners if path not in crate_by_path
    )
    # Only an explicit Cargo binding claims a compiled package exists. A
    # non-Rust module root is not a stale Cargo binding in the fallback mode.
    unregistered_bindings = sorted(
        path for path in cargo_owners if path not in crate_by_path
    )
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "canonicalModuleCount": len(modules),
        "cargoHeptaCrateCount": len(crates),
        "boundCrateCount": len(bound),
        "unclaimedCargoCrates": unclaimed,
        "ambiguousRootBindings": ambiguous,
        "modulesWithoutCargoPackage": modules_without_package,
        "declaredRootsWithoutCargoPackage": declared_without_package,
        "unregisteredBindings": unregistered_bindings,
        "unknownModules": unknown_modules,
        "status": "drift"
        if unclaimed or ambiguous or unknown_modules or unregistered_bindings
        else "aligned",
    }
    return report


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--modules", type=Path, default=DEFAULT_MODULES)
    parser.add_argument("--cargo-root", type=Path, default=DEFAULT_CARGO_ROOT)
    parser.add_argument("--strict", action="store_true", help="fail when compiled packages are unclaimed")
    parser.add_argument("--pretty", action="store_true", help="indent JSON output")
    args = parser.parse_args(argv)
    try:
        report = compare_registry(args.root, modules_path=args.modules, cargo_root=args.cargo_root)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"FAIL_HEPTA_MODULE_REGISTRY: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2 if args.pretty else None, sort_keys=True))
    if args.strict and report["status"] != "aligned":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
