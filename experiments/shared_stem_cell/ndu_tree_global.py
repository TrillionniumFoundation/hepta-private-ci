"""Read-only finite belief-DAG BSDE and exact local/global FBSDE guard.

Research-only: finite discrete chance BSDE, NOT a general stochastic FBSDE,
learned critic, real Encoder, independent verifier, or production controller.
Every input is PUBLIC information. Future labels and private world IDs are not
in the schema. The global obstruction is checked with exact rational arithmetic.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction


class StudyError(ValueError):
    pass


def q(value: str | int | Fraction) -> Fraction:
    """Canonical exact study units: reject floats, booleans and huge fractions."""
    if type(value) not in (str, int, Fraction):
        raise StudyError("exact rational required; no floating-point or bool")
    try:
        v = Fraction(value)
    except (TypeError, ValueError, ZeroDivisionError) as exc:
        raise StudyError("invalid exact rational") from exc
    if abs(v.numerator) > 10**12 or v.denominator > 10**9:
        raise StudyError("rational arithmetic budget exceeded")
    return v


@dataclass(frozen=True)
class Edge:
    name: str
    target: str
    probability: Fraction = Fraction(0)
    cost: Fraction = Fraction(0)


@dataclass(frozen=True)
class Node:
    kind: str  # terminal | or | chance | and
    public_history: tuple[str, ...]
    edges: tuple[Edge, ...] = ()
    terminal_utility: Fraction = Fraction(0)


@dataclass(frozen=True)
class TreeSolution:
    value: Fraction
    values: dict[str, Fraction]
    policy: dict[str, str]
    covariance: dict[str, Fraction]
    cross_moment: dict[str, Fraction]
    z: dict[str, Fraction]
    schema: str = "hepta.ndu.finite-public-belief-tree.v1"
    general_fbsde_solved: bool = False
    production_accepted: bool = False


def _validate(nodes: dict[str, Node], root: str) -> list[str]:
    if (type(nodes) is not dict or not 1 <= len(nodes) <= 256
            or root not in nodes or any(type(k) is not str or not k or len(k) > 96 for k in nodes)):
        raise StudyError("bounded rooted node map required")
    visited, active, order = set(), set(), []

    def visit(key: str, depth: int) -> None:
        if depth > 24 or key in active:
            raise StudyError("cycle or depth bound")
        if key in visited:
            return
        if key not in nodes:
            raise StudyError("missing child")
        node = nodes[key]
        if (type(node) is not Node or node.kind not in ("terminal", "or", "chance", "and")
                or type(node.public_history) is not tuple or len(node.public_history) > 24
                or any(type(v) is not str or not v or len(v) > 96 for v in node.public_history)):
            raise StudyError("typed public observation history required")
        if type(node.edges) is not tuple or len(node.edges) > 8:
            raise StudyError("bounded edge list required")
        if q(node.terminal_utility) != node.terminal_utility or abs(q(node.terminal_utility)) > 8:
            raise StudyError("terminal utility outside bounded profile")
        if node.kind == "terminal":
            if node.edges:
                raise StudyError("terminal cannot have outgoing edges")
        elif not (2 <= len(node.edges) <= 8):
            raise StudyError("nonterminal requires two or more transitions")
        if node.kind != "terminal" and node.terminal_utility != 0:
            raise StudyError("nonterminal reward smuggling")
        if node.kind == "chance" and len(node.edges) != 2:
            raise StudyError("pilot only supports binary public observation")
        names = []
        active.add(key)
        for edge in node.edges:
            if type(edge) is not Edge or not edge.name or len(edge.name) > 96:
                raise StudyError("typed named edge required")
            if edge.target not in nodes or edge.name in names:
                raise StudyError("missing target or duplicate action/event")
            names.append(edge.name)
            child = nodes[edge.target]
            if node.kind == "chance":
                if (not 0 < q(edge.probability) < 1 or q(edge.cost) != 0
                        or child.public_history != node.public_history + (edge.name,)):
                    raise StudyError("chance must reveal exactly one public event")
            elif (q(edge.probability) != 0 or not 0 <= q(edge.cost) <= 8
                  or child.public_history != node.public_history):
                raise StudyError("action cannot use future/unobserved information")
            if node.kind == "and" and edge.cost != 0:
                raise StudyError("AND costs require separately registered profile")
            visit(edge.target, depth + 1)
        if node.kind == "chance" and sum((e.probability for e in node.edges), Fraction()) != 1:
            raise StudyError("conditional chance probabilities must sum to one")
        if node.kind == "or":
            stop = [e for e in node.edges if e.name == "stop"]
            if len(stop) != 1 or nodes[stop[0].target].kind != "terminal" or stop[0].cost != 0:
                raise StudyError("OR must have a direct, cost-free stop action")
        active.remove(key)
        visited.add(key)
        order.append(key)

    visit(root, 0)
    if visited != set(nodes):
        raise StudyError("unreachable nodes must be removed before sealing")
    return order


def solve(nodes: dict[str, Node], root: str) -> TreeSolution:
    """Exact backward finite-BSDE value and action selection over a bounded DAG."""
    order = _validate(nodes, root)
    values: dict[str, Fraction] = {}
    policy, sigmas, bs, zs = {}, {}, {}, {}
    for key in order:
        node = nodes[key]
        if node.kind == "terminal":
            values[key] = node.terminal_utility
        elif node.kind == "or":
            actions = [(values[e.target] - e.cost, e.name) for e in node.edges]
            # Equal value chooses stop, never spend extra work without benefit.
            best, action = max(actions, key=lambda item: (item[0], item[1] == "stop"))
            values[key] = best
            policy[key] = action
        elif node.kind == "and":
            # Explicit registered bottleneck utility: ALL conjuncts required.
            values[key] = min(values[e.target] for e in node.edges)
        else:
            a, b = node.edges
            p = b.probability
            va, vb = values[a.target], values[b.target]
            values[key] = (1 - p) * va + p * vb
            # Delta M = observed_right - p; covariance = p(1-p).
            sigmas[key] = p * (1 - p)
            zs[key] = vb - va
            bs[key] = sigmas[key] * zs[key]
            if zs[key] * sigmas[key] != bs[key]:
                raise StudyError("Z Sigma != B")
    return TreeSolution(values[root], values, policy, sigmas, bs, zs)


def _forward_independent(nodes: dict[str, Node], key: str, policy: dict[str, str]) -> Fraction:
    """Independent fixed-policy forward enumeration, not cached BSDE values."""
    node = nodes[key]
    if node.kind == "terminal":
        return node.terminal_utility
    if node.kind == "or":
        chosen = [e for e in node.edges if e.name == policy[key]]
        if len(chosen) != 1:
            raise StudyError("missing selected legal action")
        edge = chosen[0]
        return _forward_independent(nodes, edge.target, policy) - edge.cost
    if node.kind == "and":
        return min(_forward_independent(nodes, e.target, policy) for e in node.edges)
    return sum((e.probability * _forward_independent(nodes, e.target, policy)
                for e in node.edges), Fraction())


def audit_finite_tree(nodes: dict[str, Node], root: str, solution: TreeSolution) -> dict:
    """Fail closed on policy, chance covariance, Bellman and forward mismatches."""
    _validate(nodes, root)
    if type(solution) is not TreeSolution or solution.general_fbsde_solved or solution.production_accepted:
        raise StudyError("unrecognized or authority-bearing solution")
    independent = _forward_independent(nodes, root, solution.policy)
    if independent != solution.value:
        raise StudyError("backward policy disagrees with independent forward enumeration")
    for key, node in nodes.items():
        if node.kind == "chance":
            a, b = node.edges
            p = b.probability
            if (solution.covariance.get(key) != p * (1 - p)
                    or solution.z.get(key) != solution.values[b.target] - solution.values[a.target]
                    or solution.z[key] * solution.covariance[key] != solution.cross_moment.get(key)
                    or solution.values[key] != sum((e.probability * solution.values[e.target]
                        for e in node.edges), Fraction())):
                raise StudyError("chance/BSDE residual")
        elif node.kind == "or":
            optimal = max(solution.values[e.target] - e.cost for e in node.edges)
            if solution.values[key] != optimal:
                raise StudyError("not an optimal OR policy")
        elif node.kind == "and":
            if solution.values[key] != min(solution.values[e.target] for e in node.edges):
                raise StudyError("missing AND obligation")
        elif node.kind == "terminal" and solution.values[key] != node.terminal_utility:
            raise StudyError("terminal condition mismatch")
    return {"finite_tree_solved": True, "forward_backward_equal": True,
            "independent_value": str(independent), "general_fbsde_solved": False,
            "independently_observed_task_success": False, "production_accepted": False}


def audit_piecewise_global(*, x0, g, horizon, segments) -> dict:
    """Exact dX=Y dt, dY=0, Y_T=g X_T; checks BOTH interface states.

    A final matching leaf, tiny local residuals, or short-horizon uniqueness is
    NEVER sufficient. Global regular-field admission additionally requires
    1-g*T > 0 for this nonnegative scalar profile.
    """
    x, gamma, t = q(x0), q(g), q(horizon)
    if not 0 <= gamma <= 8 or not 0 < t <= 8 or not 1 <= len(segments) <= 64:
        raise StudyError("unsupported profile/horizon")
    elapsed = Fraction()
    previous_x, previous_y = x, None
    max_interface_jump = Fraction()
    max_local_residual = Fraction()
    for piece in segments:
        if type(piece) not in (tuple, list) or len(piece) != 5:
            raise StudyError("segment=(h,x_start,y_start,x_end,y_end) required")
        h, xa, ya, xb, yb = map(q, piece)
        if h <= 0:
            raise StudyError("strictly positive segment")
        elapsed += h
        max_local_residual = max(max_local_residual, abs(xb - xa - h * ya), abs(yb - ya))
        max_interface_jump = max(max_interface_jump, abs(xa - previous_x))
        if previous_y is not None:
            max_interface_jump = max(max_interface_jump, abs(ya - previous_y))
        previous_x, previous_y = xb, yb
    terminal_residual = abs(previous_y - gamma * previous_x)
    regular_field = 1 - gamma * t > 0
    solution_exists = 1 - gamma * t != 0 or gamma * x == 0
    globally_solved = (elapsed == t and regular_field
                       and max_interface_jump == 0 and max_local_residual == 0
                       and terminal_residual == 0)
    return {"globally_solved": globally_solved,
            "global_regular_field_admitted": regular_field,
            "global_boundary_solution_exists": solution_exists,
            "elapsed_matches_horizon": elapsed == t,
            "max_interface_jump": str(max_interface_jump),
            "max_local_residual": str(max_local_residual),
            "terminal_residual": str(terminal_residual),
            "research_reference_only": True, "production_accepted": False}


def exact_global_segments(*, x0, g, horizon, parts: int) -> tuple:
    """Build the globally admissible solution, never reset terminal data locally."""
    x, gamma, t = q(x0), q(g), q(horizon)
    if type(parts) is not int or not 1 <= parts <= 64 or not 0 <= gamma <= 8 or 1 - gamma * t <= 0:
        raise StudyError("global regular field unavailable")
    y = gamma * x / (1 - gamma * t)
    h = t / parts
    out = []
    for _ in range(parts):
        next_x = x + h * y
        out.append((h, x, y, next_x, y))
        x = next_x
    return tuple(out)
