"""Research-only sourced graph lesion. Structural experiment, not model evidence."""
from dataclasses import dataclass
from collections import deque
import hashlib
import json

KINDS = frozenset({"supports", "precedes", "requires", "contradicts"})


@dataclass(frozen=True)
class Node:
    identity: str
    scope: str
    root: str
    generation: int
    source_digest: str


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    kind: str
    support_roots: tuple[str, ...]


@dataclass(frozen=True)
class EvalQuestion:
    seed: str
    scope: str
    generation: int
    expected: str  # Never passed into recall


class ResearchGraph:
    def __init__(self, nodes, edges):
        self.nodes = {}
        for node in nodes:
            if (not isinstance(node, Node) or not node.identity or not node.scope
                or not node.root or type(node.generation) is not int
                or node.generation < 0 or len(node.source_digest) != 64
                or node.identity in self.nodes):
                raise ValueError("invalid or duplicate node")
            self.nodes[node.identity] = node
        self.edges = []
        identities = set()
        for edge in edges:
            if (not isinstance(edge, Edge) or edge.source not in self.nodes
                or edge.target not in self.nodes or edge.kind not in KINDS
                or not edge.support_roots
                or edge.support_roots != tuple(sorted(set(edge.support_roots)))
                or (edge.source, edge.target, edge.kind) in identities
                or not set(edge.support_roots) <= {
                    self.nodes[edge.source].root, self.nodes[edge.target].root
                }):
                raise ValueError("invalid, duplicate or unsupported edge")
            identities.add((edge.source, edge.target, edge.kind))
            self.edges.append(edge)
        self.edges.sort(key=lambda e: (e.source, e.target, e.kind))

    def recall(self, seed, scope, generation, *, revoked=frozenset(),
               mode="graph", removed_edge=None, max_hops=2, max_nodes=16):
        if (seed not in self.nodes or not scope
            or mode not in {"graph", "no_graph", "shuffled", "premise_deleted"}
            or not isinstance(revoked, (set, frozenset))
            or type(generation) is not int or generation < 0
            or type(max_hops) is not int or not 0 <= max_hops <= 4
            or type(max_nodes) is not int or not 1 <= max_nodes <= 64):
            raise ValueError("invalid query")
        def eligible(identifier):
            node = self.nodes[identifier]
            return (node.scope == scope and node.generation == generation
                    and node.root not in revoked)
        if not eligible(seed):
            raise ValueError("seed denied")
        edges = [e for e in self.edges if eligible(e.source) and eligible(e.target)
                 and not (set(e.support_roots) & revoked)]
        if mode == "no_graph":
            edges = []
        if mode == "premise_deleted":
            if removed_edge is None:
                raise ValueError("premise identity required")
            edges = [e for e in edges if (e.source, e.target, e.kind) != removed_edge]
        if mode == "shuffled":
            targets = sorted({e.target for e in edges})
            if len(targets) > 1:
                replacement = {
                    target: targets[(i + len(targets) // 2) % len(targets)]
                    for i, target in enumerate(targets)
                }
                edges = [Edge(e.source, replacement[e.target], e.kind, e.support_roots)
                         for e in edges]
            else:
                edges = []
        seen, paths = {seed}, {seed: (seed,)}
        queue = deque([(seed, 0)])
        while queue and len(seen) < max_nodes:
            current, depth = queue.popleft()
            if depth >= max_hops:
                continue
            for edge in edges:
                if edge.source != current or edge.target in seen or not eligible(edge.target):
                    continue
                seen.add(edge.target)
                paths[edge.target] = paths[current] + (edge.target,)
                queue.append((edge.target, depth + 1))
                if len(seen) >= max_nodes:
                    break
        return {"nodes": tuple(sorted(seen)), "paths": paths,
                "production_accepted": False, "evidence_verified": False}


def fixture():
    nodes = [Node(f"n{i}", "scope:a", f"r{i}", 1,
                  hashlib.sha256(f"content:{i}".encode()).hexdigest())
             for i in range(12)]
    nodes += [
        Node("secret", "scope:b", "private", 1, hashlib.sha256(b"private").hexdigest()),
        Node("stale", "scope:a", "old", 0, hashlib.sha256(b"old").hexdigest()),
    ]
    edges = []
    for i in range(0, 12, 3):
        edges += [
            Edge(f"n{i}", f"n{i+1}", "precedes", tuple(sorted((f"r{i}", f"r{i+1}")))),
            Edge(f"n{i+1}", f"n{i+2}", "requires",
                 tuple(sorted((f"r{i+1}", f"r{i+2}")))),
        ]
    edges += [
        Edge("n0", "secret", "supports", ("private", "r0")),
        Edge("n3", "stale", "supports", ("old", "r3")),
    ]
    questions = [EvalQuestion(f"n{i}", "scope:a", 1, f"n{i+2}")
                 for i in range(0, 12, 3)]
    return ResearchGraph(nodes, edges), questions


def experiment():
    graph, questions = fixture()
    arms = {}
    for mode in ("no_graph", "graph", "shuffled", "premise_deleted"):
        hits = 0
        for q in questions:
            kwargs = {}
            if mode == "premise_deleted":
                kwargs["removed_edge"] = (f"n{int(q.seed[1:])+1}",
                                          q.expected, "requires")
            result = graph.recall(q.seed, q.scope, q.generation, mode=mode, **kwargs)
            if "secret" in result["nodes"] or "stale" in result["nodes"]:
                raise AssertionError("scope/generation escape")
            hits += q.expected in result["nodes"]
        arms[mode] = {"hits": hits, "questions": len(questions)}
    return {
        "schema": "hepta.memory-graph-lesion.research.v1",
        "fixture_family_count_effective": 1,
        "authored_mechanics_only": True,
        "trained_model_executed": False,
        "real_reader_executed": False,
        "strong_rag_comparison_executed": False,
        "independent_evaluation": False,
        "statistical_superiority": False,
        "production_accepted": False,
        "arms": arms,
    }


if __name__ == "__main__":
    print(json.dumps(experiment(), indent=2, sort_keys=True))
