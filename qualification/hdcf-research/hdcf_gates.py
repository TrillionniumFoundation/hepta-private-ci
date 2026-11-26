"""Research-only, fail-closed HDCF resource and reasoning-graph gates.

Not an inference driver, NDU solver, authority issuer, or executable-code loader.
Python stdlib only. All measurements must be supplied by an independent producer.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any

MAX_CELLS = 4096
MAX_NODES = 256
MAX_EDGES = 1024
MAX_DEPTH = 32
MAX_BYTES = 1_000_000


class Denied(ValueError):
    """Input is insufficient, noncanonical, or unsafe to qualify."""


def _canonical(obj: Any) -> bytes:
    try:
        payload = json.dumps(obj, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise Denied("noncanonical input") from exc
    if len(payload) > MAX_BYTES:
        raise Denied("oversized input")
    return payload


def digest(obj: Any) -> str:
    return hashlib.sha256(b"hepta.hdcf.shadow.v1\x00" + _canonical(obj)).hexdigest()


def strict_json(data: str) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for k, v in items:
            if k in result:
                raise Denied("duplicate json key")
            result[k] = v
        return result
    def reject_constant(_: str) -> None:
        raise Denied("nonfinite constant")
    if len(data.encode("utf-8")) > MAX_BYTES:
        raise Denied("oversized input")
    try:
        return json.loads(data, object_pairs_hook=pairs, parse_constant=reject_constant)
    except (ValueError, UnicodeError) as exc:
        raise Denied("invalid json") from exc


def _keys(obj: Any, expected: set[str]) -> None:
    if not isinstance(obj, dict) or set(obj) != expected:
        raise Denied("missing or unknown critical fields")


def _int(x: Any, lower: int, upper: int, label: str) -> int:
    if type(x) is not int or not lower <= x <= upper:
        raise Denied(f"invalid {label}")
    return x


def _num(x: Any, lower: float, upper: float, label: str) -> float:
    if type(x) not in (int, float) or not math.isfinite(x) or not lower <= x <= upper:
        raise Denied(f"invalid {label}")
    return float(x)


def _sha(s: Any, label: str) -> str:
    if not isinstance(s, str) or len(s) != 64 or any(c not in "0123456789abcdef" for c in s):
        raise Denied(f"invalid {label}")
    return s


def stem_cost(study: dict[str, Any]) -> dict[str, Any]:
    """Weight-only math. No RSS/FLOPs/performance or quality claim is permitted."""
    _keys(study, {"cells", "encoder_params", "head_params", "organ_params",
                  "bytes_per_weight", "same_input", "principal",
                  "encoder_digest", "input_digest", "generation"})
    n = _int(study["cells"], 1, MAX_CELLS, "cells")
    enc = _int(study["encoder_params"], 1, 10**11, "encoder parameters")
    head = _int(study["head_params"], 1, 10**8, "head parameters")
    organ = _int(study["organ_params"], 0, 10**9, "organ parameters")
    bytes_per = _int(study["bytes_per_weight"], 1, 8, "weight precision")
    _int(study["generation"], 1, 2**63 - 1, "generation")
    if not isinstance(study["same_input"], bool):
        raise Denied("same_input must be boolean")
    if not isinstance(study["principal"], str) or not study["principal"].strip() or len(study["principal"]) > 128:
        raise Denied("missing principal")
    _sha(study["encoder_digest"], "encoder digest")
    _sha(study["input_digest"], "input digest")
    duplicated = n * enc * bytes_per
    shared = (enc + organ + n * head) * bytes_per
    return {
        "claim": "WEIGHTS_ONLY_NOT_PHYSICAL_EFFICACY",
        "source_digest": digest(study),
        "duplicate_weight_bytes": duplicated,
        "shared_weight_bytes": shared,
        "savings_bytes": duplicated - shared,
        "same_input_claimed": study["same_input"],
        "encoder_forward_count": None,
        "rss_bytes": None,
        "task_quality": None,
        "production_authorized": False,
    }


@dataclass(frozen=True)
class Node:
    id: str
    parents: tuple[str, ...]
    forward_in: float
    forward_out: float
    backward_in: float
    backward_out: float
    forward_residual: float
    backward_residual: float
    cost: float


def graph_gate(plan: dict[str, Any]) -> dict[str, Any]:
    """Check a finite DAG's reported interface consistency, not global FBSDE existence.

    Explicit numeric interface checks cannot authenticate a model, stochastic
    filtration, conditional expectation, or terminal outcome. No candidate gains
    execution authorization.
    """
    _keys(plan, {"objective_digest", "source_digest", "generation", "nodes",
                 "terminal_ids", "tolerance", "budget", "declared_terminal_value"})
    _sha(plan["objective_digest"], "objective")
    _sha(plan["source_digest"], "source")
    _int(plan["generation"], 1, 2**63 - 1, "generation")
    tolerance = _num(plan["tolerance"], 0, 0.01, "tolerance")
    budget = _num(plan["budget"], 0, 1e15, "budget")
    terminal = _num(plan["declared_terminal_value"], -1e12, 1e12, "terminal")
    raw = plan["nodes"]
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_NODES:
        raise Denied("invalid nodes")
    if not isinstance(plan["terminal_ids"], list) or not plan["terminal_ids"]:
        raise Denied("missing terminal ids")
    known: dict[str, Node] = {}
    depths: dict[str, int] = {}
    children: dict[str, int] = {}
    edges = 0
    total = 0.0
    for r in raw:
        _keys(r, {"id", "parents", "forward_in", "forward_out",
                  "backward_in", "backward_out", "forward_residual",
                  "backward_residual", "cost"})
        node_id = r["id"]
        if not isinstance(node_id, str) or not node_id.isascii() or not 1 <= len(node_id) <= 64 or node_id in known:
            raise Denied("duplicate or invalid node")
        parents = r["parents"]
        if not isinstance(parents, list) or len(parents) > 16 or len(set(map(str, parents))) != len(parents):
            raise Denied("invalid parents")
        if not all(type(p) is str and p in known for p in parents):
            raise Denied("graph must be topologically ordered")
        edges += len(parents)
        if edges > MAX_EDGES:
            raise Denied("too many edges")
        depth = 1 + max((depths[p] for p in parents), default=0)
        if depth > MAX_DEPTH:
            raise Denied("graph too deep")
        values = [_num(r[k], -1e12, 1e12, k) for k in
                  ("forward_in", "forward_out", "backward_in", "backward_out")]
        fr = _num(r["forward_residual"], 0, 1e12, "forward residual")
        br = _num(r["backward_residual"], 0, 1e12, "backward residual")
        cost = _num(r["cost"], 0, 1e12, "cost")
        if fr > tolerance or br > tolerance:
            raise Denied("local residual exceeded")
        node = Node(node_id, tuple(parents), *values, fr, br, cost)
        for parent_id in parents:
            p = known[parent_id]
            if abs(p.forward_out - node.forward_in) > tolerance:
                raise Denied("forward interface discontinuity")
            if abs(p.backward_in - node.backward_out) > tolerance:
                raise Denied("backward interface discontinuity")
            children[parent_id] = children.get(parent_id, 0) + 1
        known[node_id] = node
        depths[node_id] = depth
        total += cost
        if total > budget:
            raise Denied("budget exceeded")
    tids = plan["terminal_ids"]
    if any(type(t) is not str for t in tids) or len(set(tids)) != len(tids):
        raise Denied("invalid terminal ids")
    actual_terminals = {n for n in known if children.get(n, 0) == 0}
    if set(tids) != actual_terminals:
        raise Denied("terminal coverage incomplete")
    if any(abs(known[t].backward_in - terminal) > tolerance for t in tids):
        raise Denied("terminal condition mismatch")
    return {
        "claim": "NUMERIC_DAG_INTERFACE_ONLY_NOT_GLOBAL_FBSDE",
        "plan_digest": digest(plan),
        "nodes_checked": len(raw),
        "edges_checked": edges,
        "charged_cost": total,
        "max_depth": max(depths.values()),
        "filtration_verified": False,
        "global_solution_verified": False,
        "task_success_verified": False,
        "production_authorized": False,
        "external_effect_authorized": False,
    }


def audit(document: str) -> str:
    envelope = strict_json(document)
    _keys(envelope, {"schema", "mode", "payload"})
    if envelope["schema"] != "hepta.hdcf.shadow.v1":
        raise Denied("unsupported schema")
    if envelope["mode"] == "stem_cost":
        result = stem_cost(envelope["payload"])
    elif envelope["mode"] == "graph_gate":
        result = graph_gate(envelope["payload"])
    else:
        raise Denied("unknown mode")
    return _canonical(result).decode("utf-8")


if __name__ == "__main__":
    import sys
    try:
        if len(sys.argv) != 1:
            raise Denied("no command flags accepted")
        data = sys.stdin.buffer.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise Denied("oversized stdin")
        print(audit(data.decode("utf-8")))
    except (Denied, UnicodeError) as exc:
        print(json.dumps({"disposition": "DENY_ALL", "reason": str(exc)}), file=sys.stderr)
        raise SystemExit(2) from None
