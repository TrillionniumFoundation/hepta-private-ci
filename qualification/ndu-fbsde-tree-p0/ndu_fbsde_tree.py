"""Qualification-only contracts for short-horizon NDU/FBSDE tree propagation.

This module is deliberately a shadow protocol.  It validates the boundary between
an admitted prompt, a frozen shared Stem, bounded Cell state, and a tree of local
FBSDE steps.  It does not train a neural solver, invoke a model, or grant runtime
authority.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Iterable, Mapping, Sequence


SCHEMA_NODE = "hepta.ndu.fbsde.tree-node.v1"
SCHEMA_EDGE = "hepta.ndu.fbsde.tree-edge.v1"
SCHEMA_PLAN = "hepta.ndu.fbsde.tree-plan.v1"
SCHEMA_GATE = "hepta.ndu.fbsde.shadow-gate.v1"
DENY_ALL = "DENY_ALL"
_HEX_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_FORBIDDEN_BOUNDARY_KEYS = frozenset(
    {"objective", "objective_digest", "generator", "terminal_payoff", "f", "g", "authority", "policy"}
)


class ContractError(ValueError):
    """Raised when a shadow contract is structurally unsafe or incomplete."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _finite(name: str, value: float) -> None:
    _require(isinstance(value, (int, float)) and math.isfinite(float(value)), f"{name} must be finite")


def _nonnegative(name: str, value: float) -> None:
    _finite(name, value)
    _require(float(value) >= 0.0, f"{name} must be non-negative")


def _digest(name: str, value: str) -> None:
    _require(isinstance(value, str) and _HEX_DIGEST.fullmatch(value) is not None, f"{name} must be a sha256 digest")


def _identifier(name: str, value: str) -> None:
    _require(
        isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", value) is not None,
        f"{name} is invalid",
    )


def _vector(name: str, value: Sequence[float], maximum: int) -> None:
    _require(isinstance(value, (tuple, list)) and 0 < len(value) <= maximum, f"{name} has invalid dimension")
    for item in value:
        _require(type(item) in (int, float), f"{name} element must be numeric")
        _finite(f"{name} element", item)


def digest_json(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class TreeNodeV1:
    node_id: str
    parent_id: str | None
    depth: int
    stem_digest: str
    objective_digest: str
    filtration_digest: str
    prompt_digest: str
    x: tuple[float, ...]
    h: tuple[float, ...]
    p: tuple[float, ...]
    budget: float
    continuation_lcb: float
    continuation_ucb: float
    uncertainty: float
    residual: float
    expiry_step: int

    def __post_init__(self) -> None:
        _identifier("node_id", self.node_id)
        if self.parent_id is not None:
            _identifier("parent_id", self.parent_id)
        _require(isinstance(self.depth, int) and self.depth >= 0, "depth must be a non-negative integer")
        _digest("stem_digest", self.stem_digest)
        _digest("objective_digest", self.objective_digest)
        _digest("filtration_digest", self.filtration_digest)
        _digest("prompt_digest", self.prompt_digest)
        _vector("x", self.x, 256)
        _vector("h", self.h, 256)
        _vector("p", self.p, 64)
        _nonnegative("budget", self.budget)
        _finite("continuation_lcb", self.continuation_lcb)
        _finite("continuation_ucb", self.continuation_ucb)
        _require(self.continuation_lcb <= self.continuation_ucb, "continuation interval is inverted")
        _nonnegative("uncertainty", self.uncertainty)
        _nonnegative("residual", self.residual)
        _require(isinstance(self.expiry_step, int) and self.expiry_step >= self.depth, "expiry must cover node depth")

    def boundary(self) -> dict[str, object]:
        """Only bounded state crosses a Cell/organ boundary."""
        return {
            "x": self.x,
            "h": self.h,
            "p": self.p,
            "budget": self.budget,
            "continuation_lcb": self.continuation_lcb,
            "continuation_ucb": self.continuation_ucb,
            "uncertainty": self.uncertainty,
            "residual": self.residual,
            "expiry_step": self.expiry_step,
            "filtration_digest": self.filtration_digest,
            "parent_id": self.parent_id,
        }


@dataclass(frozen=True)
class TreeEdgeV1:
    parent_id: str
    child_id: str
    dt: float
    z_residual: float
    interface_residual: float

    def __post_init__(self) -> None:
        _identifier("parent_id", self.parent_id)
        _identifier("child_id", self.child_id)
        _require(self.parent_id != self.child_id, "a tree edge cannot self-loop")
        _finite("dt", self.dt)
        _require(float(self.dt) > 0.0, "dt must be positive")
        _nonnegative("z_residual", self.z_residual)
        _nonnegative("interface_residual", self.interface_residual)


@dataclass(frozen=True)
class TreePlanV1:
    nodes: tuple[TreeNodeV1, ...]
    edges: tuple[TreeEdgeV1, ...]
    branching_factor: int
    horizon_steps: int
    max_nodes: int = 512

    def __post_init__(self) -> None:
        _require(self.nodes, "tree requires a root")
        _require(isinstance(self.branching_factor, int) and 1 <= self.branching_factor <= 64, "branching factor is invalid")
        _require(isinstance(self.horizon_steps, int) and 0 <= self.horizon_steps <= 64, "horizon is invalid")
        _require(isinstance(self.max_nodes, int) and 1 <= self.max_nodes <= 4096, "max_nodes is invalid")
        by_id = {node.node_id: node for node in self.nodes}
        _require(len(by_id) == len(self.nodes), "node ids must be unique")
        roots = [node for node in self.nodes if node.parent_id is None]
        _require(len(roots) == 1 and roots[0].depth == 0, "tree needs exactly one depth-zero root")
        _require(max(node.depth for node in self.nodes) <= self.horizon_steps, "node exceeds declared horizon")
        _require(len(self.nodes) <= self.max_nodes, "tree exceeds resource cap")
        allowed = sum(self.branching_factor**depth for depth in range(self.horizon_steps + 1))
        _require(len(self.nodes) <= allowed, "tree exceeds branching envelope")
        _require(len({node.stem_digest for node in self.nodes}) == 1, "all nodes must share the frozen Stem")
        _require(len({node.objective_digest for node in self.nodes}) == 1, "all nodes must share the fixed objective")
        _require(len({node.prompt_digest for node in self.nodes}) == 1, "all nodes must share the admitted prompt digest")
        seen_edges: set[tuple[str, str]] = set()
        for edge in self.edges:
            _require(edge.parent_id in by_id and edge.child_id in by_id, "edge references an unknown node")
            key = (edge.parent_id, edge.child_id)
            _require(key not in seen_edges, "duplicate tree edge")
            seen_edges.add(key)
            parent = by_id[edge.parent_id]
            child = by_id[edge.child_id]
            _require(child.parent_id == parent.node_id, "child parent link does not match edge")
            _require(child.depth == parent.depth + 1, "tree edges must advance one depth")
        for node in self.nodes:
            if node.parent_id is not None:
                _require(any(edge.child_id == node.node_id for edge in self.edges), "non-root node needs an incoming edge")
        _require(len(self.edges) == len(self.nodes) - 1, "a tree must have one edge per non-root node")

    @property
    def root(self) -> TreeNodeV1:
        return next(node for node in self.nodes if node.parent_id is None)

    @property
    def node_count_upper_bound(self) -> int:
        return sum(self.branching_factor**depth for depth in range(self.horizon_steps + 1))

    @property
    def state_digests(self) -> tuple[str, ...]:
        return tuple(digest_json(node.boundary()) for node in self.nodes)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": SCHEMA_PLAN,
            "nodes": len(self.nodes),
            "edges": len(self.edges),
            "branching_factor": self.branching_factor,
            "horizon_steps": self.horizon_steps,
            "max_nodes": self.max_nodes,
            "node_count_upper_bound": self.node_count_upper_bound,
            "stem_digest": self.root.stem_digest,
            "objective_digest": self.root.objective_digest,
            "prompt_digest": self.root.prompt_digest,
        }


@dataclass(frozen=True)
class FbsdeShadowGateV1:
    terminal_residual: float
    interface_residual: float
    z_residual: float
    semigroup_residual: float
    branch_global_gap: float
    interval_margin: float
    covariance_condition: float
    heldout_path_pass: bool
    boundary_immutable: bool
    prompt_injection_rejected: bool
    resource_ok: bool
    evidence_complete: bool
    residual_limit: float = 1e-3
    gap_limit: float = 1e-3
    condition_limit: float = 1e6

    def __post_init__(self) -> None:
        for name in ("terminal_residual", "interface_residual", "z_residual", "semigroup_residual", "branch_global_gap", "interval_margin", "residual_limit", "gap_limit"):
            _nonnegative(name, getattr(self, name))
        _finite("covariance_condition", self.covariance_condition)
        _require(self.covariance_condition >= 1.0, "covariance condition must be >= 1")
        _nonnegative("condition_limit", self.condition_limit)
        for name in ("heldout_path_pass", "boundary_immutable", "prompt_injection_rejected", "resource_ok", "evidence_complete"):
            _require(type(getattr(self, name)) is bool, f"{name} must be boolean")
        _require(self.residual_limit > 0.0 and self.gap_limit > 0.0 and self.condition_limit > 0.0, "gate limits must be positive")

    @property
    def passes(self) -> bool:
        return (
            self.terminal_residual <= self.residual_limit
            and self.interface_residual <= self.residual_limit
            and self.z_residual <= self.residual_limit
            and self.semigroup_residual <= self.residual_limit
            and self.branch_global_gap <= self.gap_limit
            and self.interval_margin > 0.0
            and self.covariance_condition <= self.condition_limit
            and self.heldout_path_pass
            and self.boundary_immutable
            and self.prompt_injection_rejected
            and self.resource_ok
            and self.evidence_complete
        )

    def reasons(self) -> tuple[str, ...]:
        checks = (
            (self.terminal_residual <= self.residual_limit, "terminal_residual"),
            (self.interface_residual <= self.residual_limit, "interface_residual"),
            (self.z_residual <= self.residual_limit, "z_residual"),
            (self.semigroup_residual <= self.residual_limit, "semigroup_residual"),
            (self.branch_global_gap <= self.gap_limit, "branch_global_gap"),
            (self.interval_margin > 0.0, "intervals_do_not_separate"),
            (self.covariance_condition <= self.condition_limit, "covariance_condition"),
            (self.heldout_path_pass, "heldout_path_failed"),
            (self.boundary_immutable, "boundary_mutable"),
            (self.prompt_injection_rejected, "prompt_injection_not_rejected"),
            (self.resource_ok, "resource_cap_failed"),
            (self.evidence_complete, "evidence_incomplete"),
        )
        return tuple(name for passed, name in checks if not passed)

    def advisory(self) -> dict[str, object]:
        return {
            "schema": SCHEMA_GATE,
            "decision": "ADVISORY_ACCEPT" if self.passes else "NO_GO",
            "reasons": self.reasons(),
            "authority": DENY_ALL,
            "production_activated": False,
            "model_efficacy_measured": False,
        }


_ALLOWED_PROMPT_STATE_FIELDS = frozenset(
    {
        "state", "x", "h", "p", "budget",
        "continuation_lcb", "continuation_ucb",
        "uncertainty", "residual", "expiry_step",
        "filtration_digest", "parent_id",
    }
)


def validate_prompt_boundary(prompt_digest: str, objective_digest: str, boundary: Mapping[str, object]) -> None:
    """Admit typed bounded state only; no prompt-authored solver or grant payload.

    Unknown keys, all nested objects, free-form text, nonfinite values and
    malformed identities are rejected, including protected keys hidden below
    a generic "state" wrapper. This validates a shadow *state interface*,
    not the trustworthiness of upstream raw observations.
    """
    _digest("prompt_digest", prompt_digest)
    _digest("objective_digest", objective_digest)
    _require(isinstance(boundary, Mapping), "boundary must be a mapping")
    names = set(boundary)
    _require(all(isinstance(key, str) for key in names), "boundary field names must be strings")
    _require(not (_FORBIDDEN_BOUNDARY_KEYS & names), "prompt boundary contains a protected field")
    _require("prompt_text" not in names and "raw_prompt" not in names, "raw prompt cannot cross the solver boundary")
    _require(names <= _ALLOWED_PROMPT_STATE_FIELDS, "boundary contains an unknown field")
    for name, value in boundary.items():
        if name in ("x", "h", "state"):
            _vector(name, value, 256)
        elif name == "p":
            _vector(name, value, 64)
        elif name == "filtration_digest":
            _digest(name, value)
        elif name == "parent_id":
            if value is not None:
                _identifier(name, value)
        elif name == "expiry_step":
            _require(type(value) is int and value >= 0, "expiry_step is invalid")
        else:
            _require(type(value) in (int, float), f"{name} must be numeric")
            if name in ("budget", "uncertainty", "residual"):
                _nonnegative(name, value)
            else:
                _finite(name, value)
    _require(
        ("continuation_lcb" in names) == ("continuation_ucb" in names),
        "continuation interval must have both bounds",
    )
    if "continuation_lcb" in names:
        _require(
            float(boundary["continuation_lcb"]) <= float(boundary["continuation_ucb"]),
            "continuation interval is inverted",
        )


def branch_count_upper_bound(branching_factor: int, horizon_steps: int) -> int:
    _require(isinstance(branching_factor, int) and 1 <= branching_factor <= 64, "invalid branching factor")
    _require(isinstance(horizon_steps, int) and 0 <= horizon_steps <= 64, "invalid horizon")
    return sum(branching_factor**depth for depth in range(horizon_steps + 1))


def aggregate_branch_intervals(intervals: Iterable[tuple[float, float]]) -> tuple[float, float]:
    """Aggregate conditional branch intervals; a single sampled terminal value is insufficient."""
    values = tuple(intervals)
    _require(values, "at least one branch interval is required")
    for lcb, ucb in values:
        _finite("interval lcb", lcb)
        _finite("interval ucb", ucb)
        _require(lcb <= ucb, "branch interval is inverted")
    return min(item[0] for item in values), max(item[1] for item in values)


__all__ = [
    "ContractError",
    "DENY_ALL",
    "FbsdeShadowGateV1",
    "SCHEMA_EDGE",
    "SCHEMA_GATE",
    "SCHEMA_NODE",
    "SCHEMA_PLAN",
    "TreeEdgeV1",
    "TreeNodeV1",
    "TreePlanV1",
    "aggregate_branch_intervals",
    "branch_count_upper_bound",
    "digest_json",
    "validate_prompt_boundary",
]
