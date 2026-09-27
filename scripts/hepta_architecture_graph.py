#!/usr/bin/env python3
"""Derive architecture truth from Cargo metadata and module manifests."""
from __future__ import annotations

import argparse
import json
import subprocess
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_manifests():
    result = {}
    for path in sorted((ROOT / "docs/modules").glob("*/module.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        module = value["module"]
        result[module["id"]] = value
    return result


def cargo_graph():
    output = subprocess.check_output(
        [
            "cargo",
            "metadata",
            "--no-deps",
            "--format-version=1",
            "--manifest-path",
            "codex-rs/Cargo.toml",
        ],
        cwd=ROOT,
        text=True,
    )
    metadata = json.loads(output)
    workspace = set(metadata["workspace_members"])
    packages = {
        package["id"]: package
        for package in metadata["packages"]
        if package["id"] in workspace
    }
    by_name = {package["name"]: package["id"] for package in packages.values()}
    edges = []
    for package in packages.values():
        for dependency in package.get("dependencies", []):
            target = by_name.get(dependency["name"])
            if target is not None:
                edges.append((package["name"], packages[target]["name"]))
    return sorted(package["name"] for package in packages.values()), sorted(
        set(edges)
    )


def strongly_connected(nodes, edges):
    graph = defaultdict(list)
    for left, right in edges:
        graph[left].append(right)
    index = 0
    stack = []
    on_stack = set()
    indices = {}
    low = {}
    components = []

    def visit(node):
        nonlocal index
        indices[node] = low[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for target in graph[node]:
            if target not in indices:
                visit(target)
                low[node] = min(low[node], low[target])
            elif target in on_stack:
                low[node] = min(low[node], indices[target])
        if low[node] == indices[node]:
            component = []
            while True:
                value = stack.pop()
                on_stack.remove(value)
                component.append(value)
                if value == node:
                    break
            components.append(sorted(component))

    for node in nodes:
        if node not in indices:
            visit(node)
    return sorted(component for component in components if len(component) > 1)


def render(check=False):
    packages, edges = cargo_graph()
    manifests = load_manifests()
    module_edges = sorted(
        (module_id, dependency)
        for module_id, value in manifests.items()
        for dependency in value["module"].get("uses", [])
    )
    unknown = sorted(
        {target for _, target in module_edges if target not in manifests}
    )
    if unknown:
        raise SystemExit("unknown module dependencies: " + ", ".join(unknown))
    module_scc = strongly_connected(sorted(manifests), module_edges)
    if module_scc:
        raise SystemExit(
            "module dependency cycles: " + json.dumps(module_scc)
        )
    result = {
        "schema": "hepta.compile-graph.v1",
        "schemaVersion": 1,
        "cargoPackages": packages,
        "cargoEdges": [
            {"from": left, "to": right} for left, right in edges
        ],
        "moduleEdges": [
            {"from": left, "to": right} for left, right in module_edges
        ],
        "moduleCycles": [],
        "sourceOfTruth": "cargo-metadata-and-module-manifests",
    }
    path = ROOT / "docs/modules/COMPILE_GRAPH.json"
    text = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    changed = not path.exists() or path.read_text(encoding="utf-8") != text
    if check and changed:
        raise SystemExit("COMPILE_GRAPH.json drift")
    if changed:
        path.write_text(text, encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_ARCHITECTURE_GRAPH",
                "packages": len(packages),
                "edges": len(edges),
            }
        )
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    render(args.check)


if __name__ == "__main__":
    main()
