"""Exact finite-tree BSDE reference and nonanticipative policy audit.

Research-only, scalar two-outcome martingale. This is NOT a continuous/Fully
coupled FBSDE, neural learning, production policy, or independent evaluation.
All input probabilities, terminal results and costs must come from registered,
independent observations; self-authored JSON is only a mathematical fixture.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
from fractions import Fraction

MASS = 1_000_000
MAX_NODES = 1024
MAX_DEPTH = 16
MAX_POLICIES = 65_536


class InvalidTree(ValueError):
    pass


def _natural(value, name, maximum=MASS):
    if type(value) is not int or not 0 <= value <= maximum:
        raise InvalidTree(f"invalid bounded {name}")
    return value


def _name(value):
    if type(value) is not str or not 1 <= len(value) <= 128:
        raise InvalidTree("invalid bounded identity")
    return value


def _seen(value):
    if type(value) is not list or len(value) > MAX_DEPTH or any(
        type(part) is not str or not part or len(part) > 128 for part in value
    ):
        raise InvalidTree("invalid public filtration")
    return tuple(value)


def _exact(value):
    return [value.numerator, value.denominator]


def _source(plan):
    if type(plan) is not dict or set(plan) != {"root", "nodes", "source_id"}:
        raise InvalidTree("exact source-bound tree fields required")
    _name(plan["root"])
    _name(plan["source_id"])
    nodes = plan["nodes"]
    if type(nodes) is not dict or not 1 <= len(nodes) <= MAX_NODES:
        raise InvalidTree("bounded tree inventory required")
    if plan["root"] not in nodes:
        raise InvalidTree("root missing")
    labels = {}
    for key, node in nodes.items():
        _name(key)
        if type(node) is not dict or type(node.get("kind")) is not str:
            raise InvalidTree("typed node required")
        kind = node["kind"]
        if kind not in {"terminal", "chance", "choice", "and"}:
            raise InvalidTree("unknown graph operator")
        expected = {"kind", "seen", "cost_ppm"}
        if kind == "terminal":
            expected |= {"success"}
        elif kind == "choice":
            expected |= {"info_set", "edges"}
        else:
            expected |= {"edges"}
        if set(node) != expected:
            raise InvalidTree("unknown or missing node fields")
        _seen(node["seen"])
        _natural(node["cost_ppm"], "cost")
        if kind == "terminal":
            if type(node["success"]) is not bool:
                raise InvalidTree("terminal utility must be an external boolean")
        else:
            edges = node["edges"]
            if type(edges) is not list or not edges or len(edges) > 8:
                raise InvalidTree("bounded children required")
            if kind == "chance" and len(edges) != 2:
                raise InvalidTree("scalar binomial martingale requires two outcomes")
            actions = set()
            for edge in edges:
                if type(edge) is not dict or set(edge) != (
                    {"child", "mass_ppm"} if kind == "chance" else {"child", "action"}
                    if kind == "choice" else {"child"}
                ):
                    raise InvalidTree("unexpected edge fields")
                child = _name(edge["child"])
                if child not in nodes or child in actions:
                    raise InvalidTree("missing or duplicate successor")
                actions.add(child)
                if kind == "chance":
                    _natural(edge["mass_ppm"], "martingale mass")
                    if not 0 < edge["mass_ppm"] < MASS:
                        raise InvalidTree("degenerate chance support")
                if kind == "choice":
                    _name(edge["action"])
            if kind == "chance" and sum(x["mass_ppm"] for x in edges) != MASS:
                raise InvalidTree("mass conservation violated")
            if kind == "choice":
                info = _name(node["info_set"])
                options = [_name(x["action"]) for x in edges]
                if len(options) != len(set(options)):
                    raise InvalidTree("duplicate legal action")
                view = (_seen(node["seen"]), tuple(sorted(options)))
                if info in labels and labels[info] != view:
                    raise InvalidTree("one information set changed its available information/actions")
                labels[info] = view
    # Structural admission visits ALL branches, not only winning actions.
    active, visited = set(), set()

    def visit(key, depth):
        if depth > MAX_DEPTH or key in active:
            raise InvalidTree("cycle or excessive graph depth")
        if key in visited:
            return
        active.add(key)
        node = nodes[key]
        parent = _seen(node["seen"])
        for edge in node.get("edges", []):
            child = nodes[edge["child"]]
            successor = _seen(child["seen"])
            if (len(successor) < len(parent)
                    or successor[:len(parent)] != parent):
                raise InvalidTree("future/past information was merged")
            if node["kind"] == "chance":
                if len(successor) != len(parent) + 1:
                    raise InvalidTree("chance outcome must reveal one public observation")
            elif successor != parent:
                raise InvalidTree("deterministic edge cannot reveal unseen facts")
            if node["kind"] == "and" and (child["kind"] != "terminal" or child["cost_ppm"] != 0):
                raise InvalidTree("AND is limited to zero-cost verified terminal obligations")
            visit(edge["child"], depth + 1)
        if node["kind"] == "chance":
            e0, e1 = node["edges"]
            if _seen(nodes[e0["child"]]["seen"]) == _seen(nodes[e1["child"]]["seen"]):
                raise InvalidTree("chance observations indistinguishable")
        active.remove(key)
        visited.add(key)

    visit(plan["root"], 0)
    if visited != set(nodes):
        raise InvalidTree("unreachable node inventory")
    return labels


def solve(plan, policy, *, interfaces=None):
    """Value of ONE information-set policy; never choose the lucky future.

    Chance Y=E[Y_next]-cost and Z=Y_high-Y_low with DeltaM=B-p.
    Since Var(DeltaM)=p(1-p), the conditional centered covariance regression
    recovers Z. All quantities are exact rational mathematical references.
    """
    labels = _source(plan)
    if type(policy) is not dict or set(policy) != set(labels):
        raise InvalidTree("complete frozen information-set policy required")
    for key, choice in policy.items():
        if type(choice) is not str or choice not in labels[key][1]:
            raise InvalidTree("policy selected an inadmissible action")
    nodes, values, chance_rows = plan["nodes"], {}, []
    def eval_node(key):
        if key in values:
            return values[key]
        node = nodes[key]
        cost = Fraction(node["cost_ppm"], MASS)
        kind = node["kind"]
        if kind == "terminal":
            value = Fraction(int(node["success"])) - cost
        elif kind == "and":
            value = Fraction(int(all(nodes[e["child"]]["success"] for e in node["edges"]))) - cost
        elif kind == "choice":
            edge = next(e for e in node["edges"] if e["action"] == policy[node["info_set"]])
            value = eval_node(edge["child"]) - cost
        else:
            left, right = (eval_node(e["child"]) for e in node["edges"])
            p = Fraction(node["edges"][1]["mass_ppm"], MASS)
            mean = (1 - p) * left + p * right
            value = mean - cost
            z = right - left
            covariance = p * (1 - p)
            moment = covariance * z
            residual = max(abs(left - (value + cost - p * z)),
                           abs(right - (value + cost + (1 - p) * z)),
                           abs(covariance * z - moment))
            chance_rows.append({"node": key, "Z": _exact(z),
                                "covariance": _exact(covariance),
                                "cross_moment": _exact(moment),
                                "backward_residual": _exact(residual)})
        values[key] = value
        return value

    root = eval_node(plan["root"])
    # Need all public reachable values for interface matching, including
    # counterfactual/legal alternatives (the selected policy is still frozen).
    for key in nodes:
        eval_node(key)
    maximum_error = None
    if interfaces is not None:
        if type(interfaces) is not dict or set(interfaces) != set(nodes):
            raise InvalidTree("all interfaces must be provided, not only a terminal")
        maximum_error = 0.0
        for key, offered in interfaces.items():
            if type(offered) not in (int, float) or not math.isfinite(offered):
                raise InvalidTree("nonfinite interface value")
            error = abs(float(values[key]) - offered)
            maximum_error = max(maximum_error, error)
            if error > 1e-9:
                raise InvalidTree(f"discontinuous backward interface: {key}")
    digest = hashlib.sha256(json.dumps(
        [plan, policy], sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()).hexdigest()
    return {"schema": "hepta.fbsde.finite-tree-reference.v1",
            "input_sha256": digest, "source_id": plan["source_id"],
            "root_value": _exact(root), "node_values": {k: _exact(v) for k, v in sorted(values.items())},
            "chance_conditions": sorted(chance_rows, key=lambda item: item["node"]),
            "interface_max_error": maximum_error, "interface_coverage_complete": interfaces is not None,
            "nonanticipative_policy": dict(sorted(policy.items())),
            "reference_only": True, "independent_task_evaluation": False,
            "continuous_fbsde_solved": False, "production_accepted": False}


def exact_control(plan):
    """Exhaustive *information-set* comparator for small complete finite trees."""
    labels = _source(plan)
    combinations = 1
    for _, options in labels.values():
        combinations *= len(options)
        if combinations > MAX_POLICIES:
            raise InvalidTree("exhaustive control exceeds registered policy budget")
    best_value, best_policy = None, None
    for choices in itertools.product(*(pair[1] for _, pair in sorted(labels.items()))):
        policy = dict(zip(sorted(labels), choices))
        result = solve(plan, policy)
        num, den = result["root_value"]
        value = Fraction(num, den)
        if best_value is None or value > best_value:
            best_value, best_policy = value, policy
    return {"schema": "hepta.fbsde.exact-control.v1",
            "best_value": _exact(best_value), "best_policy": best_policy,
            "enumerated_policies": combinations, "ex_ante": True,
            "production_accepted": False}
