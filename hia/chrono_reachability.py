#!/usr/bin/env python3
"""Trace chrono lock-graph paths without Cargo execution or feature inference.

Package nodes and paths are a conservative source-only analysis of a resolved
Cargo.lock. They are not proof that a feature/path executes in a given binary.
"""

import argparse
from collections import defaultdict, deque
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sys
import tomllib

from chrono_lock_audit import vendored_patch_names


@dataclass(frozen=True, order=True)
class Node:
    name: str
    version: str
    source: str

    def label(self) -> str:
        return f"{self.name}@{self.version}"


def load_graph(lock_bytes: bytes) -> tuple[dict[Node, tuple[Node, ...]], set[Node]]:
    """Resolve every declared Cargo dependency, rejecting incomplete graphs.

    A bare dependency name is permitted only if it identifies one package.
    Names with two locked versions require an explicit version in the edge.
    This deliberately rejects ambiguities rather than inventing a path.
    """
    lock = tomllib.loads(lock_bytes.decode("utf-8"))
    entries = lock.get("package")
    if not isinstance(entries, list) or not entries:
        raise ValueError("Cargo.lock has no nonempty package array")
    by_name: dict[str, list[Node]] = defaultdict(list)
    parsed: dict[Node, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("malformed Cargo.lock package")
        name, version, source = (entry.get(k) for k in ("name", "version", "source"))
        if not isinstance(name, str) or not name or not isinstance(version, str) or not version:
            raise ValueError("Cargo.lock package name/version missing")
        if source is not None and not isinstance(source, str):
            raise ValueError(f"invalid source for {name}")
        node = Node(name, version, source or "")
        if node in parsed:
            raise ValueError(f"duplicate package identity {node.label()}")
        parsed[node] = entry
        by_name[name].append(node)
    graph: dict[Node, tuple[Node, ...]] = {}
    for node, entry in parsed.items():
        deps = entry.get("dependencies", [])
        if not isinstance(deps, list) or any(not isinstance(d, str) for d in deps):
            raise ValueError(f"invalid dependency array for {node.label()}")
        resolved = []
        for spec in deps:
            fields = spec.split()
            if len(fields) not in (1, 2):
                raise ValueError(f"unsupported dependency entry in {node.label()}: {spec!r}")
            candidates = [p for p in by_name.get(fields[0], ())
                          if len(fields) == 1 or p.version == fields[1]]
            if len(candidates) != 1:
                raise ValueError(
                    f"dependency {spec!r} in {node.label()} resolves to "
                    f"{len(candidates)} package identities"
                )
            resolved.append(candidates[0])
        graph[node] = tuple(sorted(set(resolved)))
    return graph, set(parsed)


def reverse_distances(graph: dict[Node, tuple[Node, ...]], targets: set[Node]):
    """One deterministic shortest witness path to a target from every node."""
    reverse: dict[Node, set[Node]] = defaultdict(set)
    for parent, dependencies in graph.items():
        for dependency in dependencies:
            reverse[dependency].add(parent)
    distance = {t: 0 for t in targets}
    next_hop: dict[Node, Node] = {}
    queue = deque(sorted(targets))
    while queue:
        reached = queue.popleft()
        for parent in sorted(reverse[reached]):
            candidate_distance = distance[reached] + 1
            if parent not in distance:
                distance[parent] = candidate_distance
                next_hop[parent] = reached
                queue.append(parent)
            elif distance[parent] == candidate_distance and reached < next_hop[parent]:
                next_hop[parent] = reached
    return distance, next_hop


def witness(root: Node, next_hop: dict[Node, Node]) -> list[str]:
    result = [root.label()]
    while root in next_hop:
        root = next_hop[root]
        result.append(root.label())
    return result


def analyze_paths(lock_bytes: bytes, workspace_bytes: bytes) -> dict:
    graph, nodes = load_graph(lock_bytes)
    vendor = vendored_patch_names(workspace_bytes)
    chrono = {node for node in nodes if node.name == "chrono"}
    distance, next_hop = reverse_distances(graph, chrono)
    # A Cargo.lock package with no registry source is a candidate root, not
    # necessarily an actual Cargo workspace member or enabled feature.
    roots = sorted(node for node in nodes if not node.source and node.name not in vendor)
    direct_importers = {node for node, deps in graph.items() if any(d in chrono for d in deps)}
    affected = [node for node in roots if node in distance]
    direct = [node for node in affected if any(d in chrono for d in graph[node])]
    indirect = [node for node in affected if node not in direct]
    # Multi-source forward BFS obtains one shortest root-to-importer witness.
    # These roots are source-less lock entries, not proven workspace features.
    parent_from_root: dict[Node, Node] = {}
    depth: dict[Node, int] = {}
    queue = deque(roots)
    for root in roots:
        depth[root] = 0
    while queue:
        node = queue.popleft()
        for dep in graph[node]:
            new_depth = depth[node] + 1
            if dep not in depth:
                depth[dep] = new_depth
                parent_from_root[dep] = node
                queue.append(dep)
            elif new_depth == depth[dep] and node < parent_from_root.get(dep, node):
                parent_from_root[dep] = node

    external = []
    for importer in sorted(direct_importers):
        if importer.source:
            kind = "registry_external"
        elif importer.name in vendor:
            kind = "vendored_external"
        else:
            continue
        path = [importer]
        cur = importer
        while cur in parent_from_root:
            cur = parent_from_root[cur]
            path.append(cur)
        path.reverse()
        external.append({
            "importer": importer.label(),
            "kind": kind,
            "reachable_from_source_less_root": importer in depth,
            "root_to_importer_path": [p.label() for p in path] if importer in depth else None,
        })
    return {
        "schema": "codex.hia.chrono_reachability.v1",
        "scope": "resolved Cargo.lock paths, not feature-enabled/runtime evidence",
        "lock_git_blob": hashlib.sha1(b"blob " + str(len(lock_bytes)).encode()
                                       + b"\0" + lock_bytes).hexdigest(),
        "package_count": len(nodes),
        "chrono_versions": sorted({n.version for n in chrono}),
        "source_less_candidate_roots": len(roots),
        "affected_candidate_roots": len(affected),
        "direct_candidate_roots": len(direct),
        "indirect_only_candidate_roots": len(indirect),
        "root_witnesses": [
            {"root": n.label(), "path": witness(n, next_hop)} for n in affected
        ],
        "external_direct_importer_witnesses": external,
        "graph_complete": True,
        "no_chrono_package_or_edge": not chrono and not direct_importers,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lock", type=Path)
    parser.add_argument("--workspace-manifest", type=Path)
    args = parser.parse_args()
    try:
        workspace = args.workspace_manifest or args.lock.with_name("Cargo.toml")
        report = analyze_paths(args.lock.read_bytes(), workspace.read_bytes())
    except (OSError, ValueError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        print(f"chrono reachability: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
