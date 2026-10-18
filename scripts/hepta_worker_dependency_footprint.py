"""Read-only Cargo resolver closure: Worker -> Agentd direct-edge cost, NOT RSS/IPC."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re

WORKER = "codex-hepta-infer-worker-host"
AGENTD = "codex-hepta-agentd"

def closure(root: str, graph: dict[str, set[str]], omit: tuple[str, str] | None = None) -> set[str]:
    seen: set[str] = set()
    pending = [root]
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        for dependency in graph[current]:
            if (current, dependency) != omit:
                pending.append(dependency)
    return seen

def report(metadata: dict) -> dict:
    packages = metadata.get("packages")
    nodes = (metadata.get("resolve") or {}).get("nodes")
    if not isinstance(packages, list) or not 0 < len(packages) <= 30000 or not isinstance(nodes, list):
        raise ValueError("Cargo resolution is missing or unbounded")
    names = {}
    for pkg in packages:
        if not isinstance(pkg, dict) or not isinstance(pkg.get("id"), str) or not isinstance(pkg.get("name"), str):
            raise ValueError("invalid package")
        if pkg["id"] in names:
            raise ValueError("duplicate package ID")
        names[pkg["id"]] = pkg["name"]
    def one(name: str) -> str:
        ids = [key for key, value in names.items() if value == name]
        if len(ids) != 1:
            raise ValueError("missing or duplicate exact package: " + name)
        return ids[0]
    worker, agentd = one(WORKER), one(AGENTD)
    graph: dict[str, set[str]] = {}
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get("deps"), list):
            raise ValueError("missing resolver dependencies")
        key = node.get("id")
        if key not in names or key in graph:
            raise ValueError("unknown or repeated resolver node")
        values: set[str] = set()
        for edge in node["deps"]:
            if not isinstance(edge, dict) or edge.get("pkg") not in names:
                raise ValueError("unknown package edge")
            kinds = edge.get("dep_kinds")
            if not isinstance(kinds, list) or not kinds:
                raise ValueError("missing dependency kind")
            if any(isinstance(kind, dict) and kind.get("kind") in (None, "normal", "build") for kind in kinds):
                values.add(edge["pkg"])
        graph[key] = values
    if worker not in graph or agentd not in graph or any(not deps <= graph.keys() for deps in graph.values()):
        raise ValueError("unresolved graph edge")
    present = closure(worker, graph)
    omitted = closure(worker, graph, (worker, agentd))
    if not omitted <= present:
        raise ValueError("invalid counterfactual")
    removed = present - omitted
    workspace = set(metadata.get("workspace_members", []))
    def summary(ids: set[str]) -> dict:
        return {"packages": len(ids), "workspace": len(ids & workspace), "external": len(ids - workspace)}
    return {
        "schema_version": 1,
        "worker": WORKER,
        "agentd": AGENTD,
        "direct_agentd_dependency": agentd in graph[worker],
        "current": summary(present),
        "without_direct_agentd_edge": summary(omitted),
        "edge_only": {
            **summary(removed),
            "package_names_sample": sorted(names[key] for key in removed)[:128],
            "ids_sha256": hashlib.sha256("\n".join(sorted(removed)).encode()).hexdigest(),
        },
        "scope": "resolved Cargo normal/build package edges, excluding dev edges",
        "limitation": "Not a binary-size, CPU, RSS, model-memory, latency, IPC, or proof-of-safe-extraction measurement.",
    }

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--lockfile", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if re.fullmatch("[0-9a-f]{40}", args.source_sha) is None:
        parser.error("source-sha must be exact lowercase 40-character SHA")
    data = report(json.loads(args.metadata.read_text(encoding="utf-8")))
    data["source_sha"] = args.source_sha
    data["target_platform"] = args.platform
    data["cargo_lock_sha256"] = hashlib.sha256(args.lockfile.read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("Current packages:", data["current"]["packages"])
    print("Without direct Agentd edge:", data["without_direct_agentd_edge"]["packages"])
    print("Edge-only packages:", data["edge_only"]["packages"])

if __name__ == "__main__":
    main()
