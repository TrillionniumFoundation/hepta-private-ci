"""Bounded typed composition for research MemoryCells, not a production owner.

Edges contain routing metadata only. Every value passed between nodes must come
from the supplied cell reader; the graph never contains a key-to-answer table.
"""

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
import math
import random
from types import MappingProxyType


KINDS = frozenset({"semantic", "episodic", "procedural", "predictive"})


@dataclass(frozen=True)
class CellNode:
    cell_id: str
    kind: str
    input_type: str
    output_type: str
    scope: str
    artifact_id: str


@dataclass(frozen=True)
class CellEdge:
    source: str
    target: str
    relation: str


@dataclass(frozen=True)
class CellRead:
    value: str | None
    confidence: float


@dataclass(frozen=True)
class GraphStep:
    cell_id: str
    artifact_id: str
    input_digest: str
    output_digest: str | None
    confidence: float


@dataclass(frozen=True)
class GraphRead:
    value: str | None
    trace: tuple[GraphStep, ...]
    calls: int
    abstain: str | None
    generation: int


class CellUnavailable(RuntimeError):
    """The caller cannot read the named artifact at its current owner frontier."""


@dataclass(frozen=True, init=False)
class TypedGraph:
    """One immutable graph generation with separately supplied cell execution.

    ``read(cell_id, key)`` executes a cell. Optional ``route(node, value, ids)``
    chooses among already type/scope-checked successor IDs. Optional ``eligible``
    checks artifact validity immediately before each read. These callbacks must not
    receive test answers. Route computation is outside this core's call counter.
    """

    nodes: tuple[CellNode, ...]
    edges: tuple[CellEdge, ...]
    generation: int
    max_steps: int
    _nodes: MappingProxyType
    _outgoing: MappingProxyType

    def __init__(self, nodes, edges, generation=1, max_steps=4):
        nodes, edges = tuple(nodes), tuple(edges)
        if not 1 <= len(nodes) <= 256 or len(edges) > 4096:
            raise ValueError("graph resource bound")
        if (
            not isinstance(generation, int)
            or generation < 1
            or not isinstance(max_steps, int)
            or not 1 <= max_steps <= 32
        ):
            raise ValueError("invalid graph generation or step bound")
        node_map = {node.cell_id: node for node in nodes}
        if len(node_map) != len(nodes) or len(set(edges)) != len(edges):
            raise ValueError("duplicate graph identity")
        for node in nodes:
            fields = (
                node.cell_id,
                node.input_type,
                node.output_type,
                node.scope,
                node.artifact_id,
            )
            if node.kind not in KINDS or any(
                not isinstance(v, str) or not v for v in fields
            ):
                raise ValueError("invalid typed node")
        outgoing = defaultdict(list)
        for edge in edges:
            if (
                edge.source not in node_map
                or edge.target not in node_map
                or not edge.relation
            ):
                raise ValueError("unknown graph endpoint or relation")
            source, target = node_map[edge.source], node_map[edge.target]
            if source.output_type != target.input_type or source.scope != target.scope:
                raise ValueError("edge type or scope mismatch")
            outgoing[edge.source].append(edge.target)
        object.__setattr__(self, "nodes", tuple(sorted(nodes, key=lambda n: n.cell_id)))
        object.__setattr__(
            self,
            "edges",
            tuple(sorted(edges, key=lambda e: (e.source, e.target, e.relation))),
        )
        object.__setattr__(self, "generation", generation)
        object.__setattr__(self, "max_steps", max_steps)
        object.__setattr__(self, "_nodes", MappingProxyType(node_map))
        object.__setattr__(
            self,
            "_outgoing",
            MappingProxyType(
                {key: tuple(sorted(set(ids))) for key, ids in outgoing.items()}
            ),
        )

    def run(
        self,
        start: str,
        key: str,
        read: Callable,
        *,
        scope: str,
        output_type: str,
        min_confidence=0.0,
        route=None,
        eligible=None,
    ) -> GraphRead:
        if not isinstance(key, str) or not key or len(key.encode()) > 4096:
            raise ValueError("bounded string key required")
        if not math.isfinite(min_confidence) or not 0 <= min_confidence <= 1:
            raise ValueError("invalid confidence floor")
        trace, seen, calls = [], set(), 0
        current, value = start, key
        reason = "step_budget"
        for _ in range(self.max_steps):
            node = self._nodes.get(current)
            if node is None:
                reason = "unknown_node"
                break
            if node.scope != scope:
                reason = "scope_mismatch"
                break
            if eligible is not None and not eligible(node.artifact_id):
                reason = "artifact_unavailable"
                break
            if (current, value) in seen:
                reason = "cycle"
                break
            seen.add((current, value))
            try:
                calls += 1
                answer = read(current, value)
            except CellUnavailable:
                reason = "artifact_unavailable"
                break
            if not isinstance(answer, CellRead) or not math.isfinite(answer.confidence):
                raise ValueError("invalid cell read")
            if not 0 <= answer.confidence <= 1:
                raise ValueError("invalid confidence")
            if answer.value is not None and (
                not isinstance(answer.value, str)
                or not answer.value
                or len(answer.value.encode()) > 4096
            ):
                raise ValueError("invalid bounded cell value")
            trace.append(
                GraphStep(
                    current,
                    node.artifact_id,
                    sha256(value.encode()).hexdigest(),
                    sha256(answer.value.encode()).hexdigest() if answer.value else None,
                    answer.confidence,
                )
            )
            if answer.value is None or answer.confidence < min_confidence:
                reason = "cell_abstained"
                break
            value = answer.value
            if node.output_type == output_type:
                return GraphRead(value, tuple(trace), calls, None, self.generation)
            candidates = self._outgoing.get(current, ())
            if not candidates:
                reason = "missing_edge"
                break
            if len(candidates) == 1:
                current = candidates[0]
            elif route is None:
                reason = "ambiguous_route"
                break
            else:
                current = route(node, value, candidates)
                if current not in candidates:
                    reason = "inadmissible_route"
                    break
        return GraphRead(None, tuple(trace), calls, reason, self.generation)

    def no_edges(self):
        return TypedGraph(self.nodes, (), self.generation, self.max_steps)

    def shuffled_edges(self, seed):
        """Permute target identities within type/scope, preserving all bounds.

        A singleton target group cannot be shuffled. Consumers must report how many
        edges actually changed, rather than interpreting an identity shuffle as evidence.
        """
        groups = defaultdict(set)
        for edge in self.edges:
            node = self._nodes[edge.target]
            groups[(node.input_type, node.scope)].add(node.cell_id)
        mapping, rng = {}, random.Random(seed)
        for group in sorted(groups):
            original = sorted(groups[group])
            shuffled = original.copy()
            rng.shuffle(shuffled)
            if len(original) > 1 and shuffled == original:
                shuffled = shuffled[1:] + shuffled[:1]
            mapping.update(zip(original, shuffled))
        edges = tuple(
            CellEdge(e.source, mapping[e.target], e.relation) for e in self.edges
        )
        return TypedGraph(self.nodes, edges, self.generation, self.max_steps)
