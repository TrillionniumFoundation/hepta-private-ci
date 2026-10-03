#!/usr/bin/env python3
"""Project and enforce the real Cargo architecture graph.

Production and development dependencies are separate.  Production edges must
flow from a strictly higher ``compileLayer`` to a lower layer and both package
and module production graphs must remain acyclic.  Logical ``uses`` edges stay
visible as a distinct semantic graph rather than pretending to be Cargo truth.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MATRIX = Path("docs/modules/CI_MATRIX.json")
MODULES = Path("docs/modules/MODULES.json")
OUTPUT = Path("docs/modules/COMPILE_GRAPH.json")


def cargo_metadata(root: Path) -> dict[str, Any]:
    return json.loads(
        subprocess.check_output(
            [
                "cargo",
                "metadata",
                "--locked",
                "--no-deps",
                "--format-version=1",
                "--manifest-path",
                str(root / "codex-rs/Cargo.toml"),
            ],
            cwd=root,
            text=True,
        )
    )


def load_inputs(root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    metadata = cargo_metadata(root)
    matrix = json.loads((root / MATRIX).read_text(encoding="utf-8"))
    modules = json.loads((root / MODULES).read_text(encoding="utf-8"))
    if matrix.get("schema") != "hepta.module-ci-matrix.v1":
        raise ValueError("unsupported module CI matrix")
    if modules.get("schema") != "hepta.module-registry.v7":
        raise ValueError("unsupported module registry")
    return metadata, matrix, modules


def strongly_connected(nodes: set[str], edges: set[tuple[str, str]]) -> list[list[str]]:
    graph: dict[str, list[str]] = defaultdict(list)
    for source, target in sorted(edges):
        graph[source].append(target)
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[list[str]] = []

    def visit(node: str) -> None:
        index[node] = low[node] = len(index)
        stack.append(node)
        on_stack.add(node)
        for target in graph[node]:
            if target not in index:
                visit(target)
                low[node] = min(low[node], low[target])
            elif target in on_stack:
                low[node] = min(low[node], index[target])
        if low[node] == index[node]:
            component: list[str] = []
            while True:
                current = stack.pop()
                on_stack.remove(current)
                component.append(current)
                if current == node:
                    break
            if len(component) > 1:
                components.append(sorted(component))

    for node in sorted(nodes):
        if node not in index:
            visit(node)
    return sorted(components)


def _edge_row(
    source: dict[str, Any],
    target: dict[str, Any],
    dependency_kind: str,
) -> dict[str, Any]:
    return {
        "fromPackage": source["packageName"],
        "toPackage": target["packageName"],
        "fromModule": source["module"],
        "toModule": target["module"],
        "fromLayer": source["compileLayer"],
        "toLayer": target["compileLayer"],
        "dependencyKind": dependency_kind,
    }


def _dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique = {json.dumps(row, sort_keys=True): row for row in rows}
    return [unique[key] for key in sorted(unique)]


def build_report(
    metadata: dict[str, Any],
    matrix: dict[str, Any],
    modules_document: dict[str, Any],
) -> dict[str, Any]:
    packages: dict[str, dict[str, Any]] = {}
    package_paths: set[str] = set()
    module_ids = {row["id"] for row in modules_document.get("modules", [])}
    for row in matrix.get("packages", []):
        name = row.get("packageName")
        path = row.get("packagePath")
        module = row.get("module")
        layer = row.get("compileLayer")
        if (
            not isinstance(name, str)
            or not isinstance(path, str)
            or not isinstance(module, str)
            or module not in module_ids
            or not isinstance(layer, int)
            or layer < 0
        ):
            raise ValueError(f"invalid compile graph package row: {row!r}")
        if name in packages or path in package_paths:
            raise ValueError(f"duplicate compile graph package: {name} / {path}")
        package_paths.add(path)
        packages[name] = row

    metadata_packages = {row["name"]: row for row in metadata.get("packages", [])}
    missing = sorted(set(packages) - set(metadata_packages))
    if missing:
        raise ValueError(f"manifest packages missing from Cargo metadata: {missing}")
    unbound = sorted(
        name
        for name in metadata_packages
        if name.startswith("codex-hepta-") and name not in packages
    )
    if unbound:
        raise ValueError(f"unbound Hepta Cargo packages: {unbound}")
    for name, row in packages.items():
        actual_manifest = Path(metadata_packages[name]["manifest_path"]).as_posix()
        expected_manifest = row["packagePath"].rstrip("/") + "/Cargo.toml"
        if not (
            actual_manifest == expected_manifest
            or actual_manifest.endswith("/" + expected_manifest)
        ):
            raise ValueError(
                f"Cargo manifest path mismatch for {name}: {actual_manifest} != {expected_manifest}"
            )

    production_rows: list[dict[str, Any]] = []
    development_rows: list[dict[str, Any]] = []
    external_rows: list[dict[str, Any]] = []
    for package in metadata.get("packages", []):
        source = packages.get(package["name"])
        for dependency in package.get("dependencies", []):
            target = packages.get(dependency["name"])
            kind = dependency.get("kind") or "normal"
            if source is not None and target is not None:
                row = _edge_row(source, target, kind)
                if kind == "dev":
                    development_rows.append(row)
                else:
                    production_rows.append(row)
            elif source is None and target is not None:
                external_rows.append(
                    {
                        "consumerPackage": package["name"],
                        "heptaPackage": target["packageName"],
                        "heptaModule": target["module"],
                        "dependencyKind": kind,
                    }
                )

    production_rows = _dedupe_rows(production_rows)
    development_rows = _dedupe_rows(development_rows)
    external_rows = _dedupe_rows(external_rows)
    layer_violations = [
        row
        for row in production_rows
        if row["fromPackage"] != row["toPackage"] and row["fromLayer"] <= row["toLayer"]
    ]
    package_edges = {
        (row["fromPackage"], row["toPackage"])
        for row in production_rows
        if row["fromPackage"] != row["toPackage"]
    }
    package_cycles = strongly_connected(set(packages), package_edges)

    production_module_edges = {
        (row["fromModule"], row["toModule"])
        for row in production_rows
        if row["fromModule"] != row["toModule"]
    }
    development_module_edges = {
        (row["fromModule"], row["toModule"])
        for row in development_rows
        if row["fromModule"] != row["toModule"]
    }
    module_cycles = strongly_connected(module_ids, production_module_edges)
    logical_edges = {
        (row["id"], dependency)
        for row in modules_document.get("modules", [])
        for dependency in row.get("uses", [])
        if row["id"] != dependency
    }

    physical_only = sorted(production_module_edges - logical_edges)
    logical_only = sorted(logical_edges - production_module_edges)
    violations = {
        "layerDirection": layer_violations,
        "productionPackageCycles": package_cycles,
        "productionModuleCycles": module_cycles,
    }
    aligned = not any(violations.values())
    return {
        "schema": "hepta.compile-architecture-graph.v1",
        "generatedFrom": [
            "cargo metadata --locked --no-deps",
            "docs/modules/*/module.toml",
        ],
        "status": "aligned" if aligned else "architecture_violation",
        "packages": [
            {
                "packageName": row["packageName"],
                "packagePath": row["packagePath"],
                "module": row["module"],
                "compileLayer": row["compileLayer"],
            }
            for row in sorted(packages.values(), key=lambda item: item["packageName"])
        ],
        "productionPackageEdges": production_rows,
        "developmentPackageEdges": development_rows,
        "productionModuleEdges": [
            {"fromModule": source, "toModule": target}
            for source, target in sorted(production_module_edges)
        ],
        "developmentModuleEdges": [
            {"fromModule": source, "toModule": target}
            for source, target in sorted(development_module_edges)
        ],
        "logicalModuleEdges": [
            {"fromModule": source, "toModule": target}
            for source, target in sorted(logical_edges)
        ],
        "physicalOnlyModuleEdges": [
            {"fromModule": source, "toModule": target}
            for source, target in physical_only
        ],
        "logicalOnlyModuleEdges": [
            {"fromModule": source, "toModule": target}
            for source, target in logical_only
        ],
        "externalHostConsumers": external_rows,
        "violations": violations,
    }


def render_report(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True) + "\n"


def apply(root: Path, *, check: bool) -> dict[str, Any]:
    metadata, matrix, modules = load_inputs(root)
    report = build_report(metadata, matrix, modules)
    output = root / OUTPUT
    expected = render_report(report)
    actual = output.read_text(encoding="utf-8") if output.is_file() else ""
    if check and actual != expected:
        raise ValueError(f"generated compile graph drift: {OUTPUT}")
    if not check and actual != expected:
        output.write_text(expected, encoding="utf-8")
    if report["status"] != "aligned":
        raise ValueError(
            "Cargo architecture violations: "
            + json.dumps(report["violations"], sort_keys=True)
        )
    return report


def validate_client_profile_tree(text: str) -> dict[str, Any]:
    """Check resolved normal/build features, never the all-feature metadata union."""
    packages: dict[str, set[str]] = {}
    for line in text.splitlines():
        identity, separator, features = line.partition("|")
        if not separator or not identity.strip():
            raise ValueError("invalid client Cargo tree row")
        name = identity.split()[0]
        enabled = {item for item in features.removesuffix(" (*)").split(",") if item}
        packages.setdefault(name, set()).update(enabled)
    if "codex-hepta-agentd" not in packages:
        raise ValueError("client Cargo tree omitted the actual Agentd root")
    forbidden = {
        name
        for name in packages
        if name
        in {
            "codex-state",
            "codex-core",
            "codex-app-server",
            "codex-hepta-agent-components",
            "codex-hepta-operations",
        }
        or name.startswith(("sqlx", "rusqlite", "libsqlite3-sys"))
    }
    for name, feature in (
        ("codex-hepta-agentd", "server"),
        ("codex-hepta-automation", "runtime"),
        ("codex-hepta-evidence", "runtime"),
    ):
        if feature in packages.get(name, set()):
            forbidden.add(f"{name}/{feature}")
    if forbidden:
        raise ValueError(
            "client profile links runtime/store code: " + ", ".join(sorted(forbidden))
        )
    return {
        "status": "PASS_HEPTA_CLIENT_PROFILE",
        "root": "codex-hepta-agentd",
        "edges": ["normal", "build"],
        "packages": sorted(packages),
        "features": {name: sorted(values) for name, values in sorted(packages.items())},
    }


def check_client_profile(root: Path) -> dict[str, Any]:
    tree = subprocess.check_output(
        [
            "cargo",
            "tree",
            "--locked",
            "--manifest-path",
            str(root / "codex-rs/Cargo.toml"),
            "-p",
            "codex-hepta-agentd",
            "--no-default-features",
            "--edges",
            "normal,build",
            "--prefix",
            "none",
            "--format",
            "{p}|{f}",
        ],
        cwd=root,
        text=True,
    )
    return validate_client_profile_tree(tree)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check-client-profile", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        if args.check_client_profile:
            print(json.dumps(check_client_profile(args.root.resolve()), sort_keys=True))
            return 0
        report = apply(args.root.resolve(), check=args.check)
    except (
        OSError,
        ValueError,
        KeyError,
        json.JSONDecodeError,
        subprocess.CalledProcessError,
    ) as error:
        print(f"FAIL_HEPTA_ARCHITECTURE_GRAPH: {error}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_ARCHITECTURE_GRAPH",
                "packageCount": len(report["packages"]),
                "productionPackageEdgeCount": len(report["productionPackageEdges"]),
                "developmentPackageEdgeCount": len(report["developmentPackageEdges"]),
                "productionModuleEdgeCount": len(report["productionModuleEdges"]),
                "physicalOnlyModuleEdgeCount": len(report["physicalOnlyModuleEdges"]),
                "logicalOnlyModuleEdgeCount": len(report["logicalOnlyModuleEdges"]),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
