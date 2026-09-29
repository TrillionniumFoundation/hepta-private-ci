#!/usr/bin/env python3
"""Generate all module registry, Cargo ownership and CI views from module.toml.

The only hand-maintained module rows live at
``docs/modules/<module-id>/module.toml``.  ``MODULES.json``,
``CARGO_BINDINGS.json``, ``SOURCE_BINDINGS.json``, ``MODULE_DOCS.json`` and
``CI_MATRIX.json`` are projections and must never be edited independently.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tomllib
from collections import OrderedDict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MODULE_ROOT = ROOT / "docs/modules"
REGISTRY = MODULE_ROOT / "registry.toml"
MODULES_JSON = MODULE_ROOT / "MODULES.json"
CARGO_JSON = MODULE_ROOT / "CARGO_BINDINGS.json"
SOURCE_JSON = MODULE_ROOT / "SOURCE_BINDINGS.json"
CI_JSON = MODULE_ROOT / "CI_MATRIX.json"
DOCS_JSON = MODULE_ROOT / "MODULE_DOCS.json"
ALL_CI_GROUPS = ("effects", "inference", "learning", "lifecycle", "objective")

MODULE_KEYS = (
    "id",
    "plane",
    "kind",
    "lifecycle",
    "state",
    "architectureRole",
    "writes",
    "uses",
    "owner",
    "deputy",
    "denies",
    "localHotPathCentralRpc",
    "rootBindings",
    "hotPathPolicy",
    "publicSurfacePolicy",
    "sourceStatus",
    "source_root_present",
    "production_implementation",
    "sourceEvidenceRoots",
    "missingDeclaredRoots",
    "bootstrapWorkPackage",
    "technicalDocument",
    "documentationReady",
)


def render_json(document: Any) -> str:
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_manifests(
    root: Path = ROOT,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    module_root = root / "docs/modules"
    registry_path = module_root / "registry.toml"
    if not registry_path.is_file():
        raise ValueError(f"missing module registry manifest: {registry_path}")
    registry = tomllib.loads(registry_path.read_text(encoding="utf-8"))
    if registry.get("schema") != "hepta.module-manifest-registry.v1":
        raise ValueError("unsupported registry manifest schema")

    modules: list[dict[str, Any]] = []
    cargo_rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_orders: set[int] = set()
    orders: dict[str, int] = {}
    seen_packages: dict[str, str] = {}
    for path in sorted(module_root.glob("*/module.toml")):
        document = tomllib.loads(path.read_text(encoding="utf-8"))
        if document.get("schema") != "hepta.module-manifest.v1":
            raise ValueError(f"{path}: unsupported module manifest schema")
        module_id = document.get("id")
        if not isinstance(module_id, str) or module_id != path.parent.name:
            raise ValueError(f"{path}: id must match its directory")
        if module_id in seen_ids:
            raise ValueError(f"duplicate module id: {module_id}")
        seen_ids.add(module_id)
        order = document.get("order")
        if not isinstance(order, int) or order < 0 or order in seen_orders:
            raise ValueError(f"{path}: order must be a unique non-negative integer")
        seen_orders.add(order)
        orders[module_id] = order
        missing = [key for key in MODULE_KEYS if key not in document]
        if missing:
            raise ValueError(f"{path}: missing fields: {', '.join(missing)}")
        modules.append(OrderedDict((key, document[key]) for key in MODULE_KEYS))
        packages = document.get("cargoPackages", [])
        if not isinstance(packages, list):
            raise ValueError(f"{path}: cargoPackages must be an array of tables")
        for package in packages:
            package_path = package.get("path") if isinstance(package, dict) else None
            groups = package.get("ciGroups") if isinstance(package, dict) else None
            compile_layer = (
                package.get("compileLayer") if isinstance(package, dict) else None
            )
            if not isinstance(package_path, str) or not package_path.startswith(
                "codex-rs/"
            ):
                raise ValueError(f"{path}: invalid Cargo package path")
            if package_path in seen_packages:
                raise ValueError(
                    f"Cargo package {package_path} owned by both {seen_packages[package_path]} and {module_id}"
                )
            if not isinstance(groups, list) or any(
                group not in ALL_CI_GROUPS for group in groups
            ):
                raise ValueError(f"{path}: invalid ciGroups for {package_path}")
            if not isinstance(compile_layer, int) or compile_layer < 0:
                raise ValueError(
                    f"{path}: compileLayer must be a non-negative integer for {package_path}"
                )
            seen_packages[package_path] = module_id
            manifest = root / package_path / "Cargo.toml"
            if not manifest.is_file():
                raise ValueError(
                    f"{path}: missing Cargo manifest {package_path}/Cargo.toml"
                )
            cargo = tomllib.loads(manifest.read_text(encoding="utf-8"))
            package_name = cargo.get("package", {}).get("name")
            if not isinstance(package_name, str) or not package_name.startswith(
                "codex-hepta-"
            ):
                raise ValueError(f"{manifest}: not a codex-hepta package")
            cargo_rows.append(
                {
                    "packagePath": package_path,
                    "packageName": package_name,
                    "module": module_id,
                    "ciGroups": sorted(set(groups)),
                    "compileLayer": compile_layer,
                }
            )

    modules.sort(key=lambda module: orders[module["id"]])
    ids = {module["id"] for module in modules}
    for module in modules:
        unknown = sorted(set(module["uses"]) - ids)
        if unknown:
            raise ValueError(
                f"{module['id']}: unknown semantic dependencies: {unknown}"
            )
        roots = [binding.get("path") for binding in module["rootBindings"]]
        if any(not isinstance(value, str) or not value for value in roots):
            raise ValueError(f"{module['id']}: invalid rootBindings")
    if not modules:
        raise ValueError("no module manifests found")
    return registry, modules, sorted(cargo_rows, key=lambda row: row["packagePath"])


def projected_documents(root: Path = ROOT) -> dict[Path, str]:
    registry, modules, cargo_rows = load_manifests(root)
    projection = registry.get("projection")
    if not isinstance(projection, dict):
        raise ValueError("registry.toml: missing [projection]")
    module_document: OrderedDict[str, Any] = OrderedDict()
    for key in (
        "schema",
        "schemaVersion",
        "documentClass",
        "authorityScope",
        "planId",
        "planVersion",
    ):
        if key not in projection:
            raise ValueError(f"registry.toml: projection.{key} missing")
        module_document[key] = projection[key]
    for key in ("defaults", "rules"):
        value = registry.get(key)
        if not isinstance(value, dict):
            raise ValueError(f"registry.toml: [{key}] missing")
        module_document[key] = value
    module_document["modules"] = modules
    authority = registry.get("authorityFlags")
    if not isinstance(authority, dict):
        raise ValueError("registry.toml: [authorityFlags] missing")
    module_document["authorityFlags"] = authority

    cargo_document = {
        "schema": "hepta.cargo-module-binding.v1",
        "bindings": [
            {"packagePath": row["packagePath"], "module": row["module"]}
            for row in cargo_rows
        ],
    }
    ci_document = {
        "schema": "hepta.module-ci-matrix.v1",
        "generatedFrom": "docs/modules/*/module.toml",
        "groups": list(ALL_CI_GROUPS),
        "packages": cargo_rows,
    }

    source_template = load_json(root / "docs/modules/SOURCE_BINDINGS.json")
    source_template["bindings"] = []
    for module in modules:
        declared = [binding["path"] for binding in module["rootBindings"]]
        existing = [value for value in declared if (root / value).exists()]
        source_template["bindings"].append(
            {
                "module": module["id"],
                "lifecycle": module["lifecycle"],
                "sourceStatus": module["sourceStatus"],
                "source_root_present": module["source_root_present"],
                "production_implementation": module["production_implementation"],
                "declaredRoots": declared,
                "existingDeclaredRoots": existing,
                "sourceEvidenceRoots": module["sourceEvidenceRoots"],
                "missingDeclaredRoots": [
                    value for value in declared if value not in existing
                ],
                "bootstrapWorkPackage": module["bootstrapWorkPackage"],
                "technicalDocument": module["technicalDocument"],
            }
        )

    return {
        root / "docs/modules/MODULES.json": render_json(module_document),
        root / "docs/modules/CARGO_BINDINGS.json": render_json(cargo_document),
        root / "docs/modules/CI_MATRIX.json": render_json(ci_document),
        root / "docs/modules/SOURCE_BINDINGS.json": render_json(source_template),
    }


def apply(check: bool, root: Path = ROOT) -> list[str]:
    projections = projected_documents(root)
    changed: list[str] = []
    for path, expected in projections.items():
        actual = path.read_text(encoding="utf-8") if path.is_file() else ""
        if actual != expected:
            changed.append(path.relative_to(root).as_posix())
            if not check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(expected, encoding="utf-8")
    return changed


def run_docs_projection(root: Path, check: bool) -> None:
    # Repeated machine facts remain generated, but ordinary development must
    # never require prose byte counts, word counts or guide SHA refreshes.
    # Those optional presentation metrics are release/audit-only through the
    # explicit ``hepta_module_doc_metadata.py --write --prose-metrics`` path.
    command = [
        sys.executable,
        str(root / "scripts/hepta-module-docs.py"),
        "refresh-derived",
    ]
    if check:
        command.append("--check")
    subprocess.run(command, cwd=root, check=True)
    command = [sys.executable, str(root / "scripts/hepta_module_doc_metadata.py")]
    if not check:
        command.append("--write")
    subprocess.run(command, cwd=root, check=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        changed = apply(args.check, args.root)
        if args.check and changed:
            raise ValueError("generated projection drift: " + ", ".join(changed))
        run_docs_projection(args.root, args.check)
    except (
        OSError,
        ValueError,
        subprocess.CalledProcessError,
        tomllib.TOMLDecodeError,
        json.JSONDecodeError,
    ) as error:
        print(f"FAIL_HEPTA_MODULE_MANIFEST: {error}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_MODULE_MANIFEST"
                if args.check
                else "UPDATED_HEPTA_MODULE_MANIFEST",
                "source": "docs/modules/*/module.toml",
                "changed": changed,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
