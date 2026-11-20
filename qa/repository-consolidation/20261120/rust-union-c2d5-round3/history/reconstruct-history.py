#!/usr/bin/env python3
"""Rebuild the audited complete graph from published parts and new nodes."""

import argparse
from collections import deque
import gzip
import hashlib
import json
from pathlib import Path
import re


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git_blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def parse_graph(data):
    graph = {}
    for line in data.decode("ascii").splitlines():
        fields = line.split()
        if not fields or any(
            not re.fullmatch(r"[0-9a-f]{40}", item) for item in fields
        ):
            raise ValueError("Invalid graph row")
        if fields[0] in graph:
            raise ValueError("Duplicate graph node")
        graph[fields[0]] = fields[1:]
    return graph


def reconstruct(repo, manifest_path):
    manifest = json.loads(manifest_path.read_text())
    chunks = []
    for part in manifest["baseline"]["parts"]:
        relative = Path(part["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Invalid baseline path")
        raw = (repo / relative).read_bytes()
        if (
            git_blob(raw) != part["git_blob"]
            or digest(raw) != part["compressed_sha256"]
        ):
            raise ValueError("Published baseline part identity mismatch")
        chunk = gzip.decompress(raw)
        if digest(chunk) != part["uncompressed_sha256"]:
            raise ValueError("Published baseline part content mismatch")
        chunks.append(chunk)
    baseline = b"".join(chunks)
    if digest(baseline) != manifest["baseline"]["complete_sha256"]:
        raise ValueError("Complete published baseline mismatch")
    graph = parse_graph(baseline)
    if len(graph) != manifest["baseline"]["nodes"]:
        raise ValueError("Baseline node count mismatch")
    original = dict(graph)
    delta_bytes = (manifest_path.parent / manifest["delta_file"]).read_bytes()
    if digest(delta_bytes) != manifest["delta_sha256"]:
        raise ValueError("Delta identity mismatch")
    delta = json.loads(delta_bytes)
    additions = parse_graph("".join(delta["new_parent_rows"]).encode("ascii"))
    if graph.keys() & additions.keys():
        raise ValueError("Delta attempted to replace a historical parent vector")
    if len(additions) != manifest["delta_nodes"]:
        raise ValueError("Delta node count mismatch")
    graph.update(additions)
    if any(graph[node] != parents for node, parents in original.items()):
        raise ValueError("A historical ordered parent vector changed")

    # The previous server audit serialized its node map in SHA order. The new
    # server commits and HIA observations were then inserted in this
    # recorded order. Stable FIFO Kahn traversal reproduces its exact bytes.
    late = delta["late_insertion_order"]
    if len(late) != len(set(late)) or not set(late) <= additions.keys():
        raise ValueError("Invalid final insertion order")
    insertion = sorted(graph.keys() - set(late)) + late
    children = {node: [] for node in insertion}
    degrees = {}
    for node in insertion:
        degrees[node] = len(graph[node])
        for parent in graph[node]:
            if parent not in graph:
                raise ValueError("Missing parent")
            children[parent].append(node)
    ready = deque(node for node in insertion if degrees[node] == 0)
    order = []
    while ready:
        node = ready.popleft()
        order.append(node)
        for child in children[node]:
            degrees[child] -= 1
            if degrees[child] == 0:
                ready.append(child)
    if len(order) != len(graph):
        raise ValueError("Commit graph contains a cycle")
    result = "".join(" ".join([node, *graph[node]]) + "\n" for node in order).encode(
        "ascii"
    )
    expected = manifest["reconstructed"]
    if (
        len(result) != expected["bytes"]
        or len(graph) != expected["nodes"]
        or digest(result) != expected["sha256"]
    ):
        raise ValueError("Reconstructed complete graph mismatch")
    return result, {
        "status": "VERIFIED",
        "baseline_nodes_unchanged": len(original),
        "new_nodes": len(additions),
        "nodes": len(graph),
        "bytes": len(result),
        "sha256": digest(result),
        "missing_parents": [],
        "cycles": False,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        type=Path,
        required=True,
        help="Checkout containing the published qa/history parts",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).with_name("history-manifest.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional reconstructed graph output; omitted performs verification only",
    )
    args = parser.parse_args()
    graph_bytes, receipt = reconstruct(args.repo, args.manifest)
    if args.output is not None:
        args.output.write_bytes(graph_bytes)
    print(json.dumps(receipt, indent=2))
