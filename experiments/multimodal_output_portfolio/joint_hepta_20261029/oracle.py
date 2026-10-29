"""Independent finite-DAG entropic control and policy-gradient references.

These are mathematical oracles for a declared finite joint law. Terminal labels
are allowed here as enumerated model outcomes, never as live policy features.
The production learner must not claim this tiny exact solution covers its latent
state space. All costs remain inside the same branch as terminal quality.
"""

from dataclasses import dataclass
from itertools import product
import math

from ..unified_20261028.profile import certainty_equivalent


@dataclass(frozen=True)
class Branch:
    probability: float
    cost: float = 0.0
    next_state: str | None = None
    terminal_utility: float | None = None


@dataclass(frozen=True)
class PathOutcome:
    probability: float
    net_return: float
    decisions: tuple[tuple[str, str], ...]


def _finite(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def validate_problem(nodes, root, gamma):
    if (not _finite(gamma) or gamma <= 0 or not isinstance(nodes, dict)
            or root not in nodes or len(nodes) > 512):
        raise ValueError("A finite explicit risk problem and positive gamma are required")
    for name, actions in nodes.items():
        if not isinstance(name, str) or not name or not isinstance(actions, dict) or not actions:
            raise ValueError("Every state needs an explicit nonempty action set")
        for action, branches in actions.items():
            if not isinstance(action, str) or not action or not isinstance(branches, tuple) or not branches:
                raise ValueError("Actions need complete immutable outcome laws")
            for branch in branches:
                if (not isinstance(branch, Branch) or not _finite(branch.probability)
                        or branch.probability <= 0 or not _finite(branch.cost) or branch.cost < 0
                        or (branch.next_state is None) == (branch.terminal_utility is None)
                        or branch.next_state is not None and branch.next_state not in nodes
                        or branch.terminal_utility is not None and not _finite(branch.terminal_utility)):
                    raise ValueError("Invalid joint transition/terminal branch")
            if not math.isclose(math.fsum(b.probability for b in branches), 1.0,
                                abs_tol=1e-12, rel_tol=0):
                raise ValueError("Missing branch mass; do not normalize away failures")
    active, complete = set(), set()

    def visit(state):
        if state in active:
            raise ValueError("Include a finite horizon in state; cyclic oracles are unsupported")
        if state in complete:
            return
        active.add(state)
        for branches in nodes[state].values():
            for branch in branches:
                if branch.next_state is not None:
                    visit(branch.next_state)
        active.remove(state)
        complete.add(state)

    for state in nodes:
        visit(state)


def solve_risk_dp(nodes, root, gamma=2.0):
    """Exact conditional CE Bellman solution on the supplied finite DAG.

Delivery/stop is an ordinary action with its full stochastic terminal law.
Lexicographic action order resolves exact ties, independently of input order.
"""
    validate_problem(nodes, root, gamma)
    values, action_values, policy = {}, {}, {}

    def solve(state):
        if state in values:
            return values[state]
        q = {}
        for action in sorted(nodes[state]):
            branches = nodes[state][action]
            returns = [(solve(b.next_state) if b.next_state is not None else b.terminal_utility)
                       - b.cost for b in branches]
            q[action] = certainty_equivalent(returns, gamma, [b.probability for b in branches])
        selected = max(sorted(q), key=q.get)
        values[state], action_values[state], policy[state] = q[selected], q, selected
        return values[state]

    value = solve(root)
    return {"value": value, "values": values, "action_values": action_values, "policy": policy}


def _policy(nodes, supplied):
    if set(supplied) != set(nodes):
        raise ValueError("Policy must cover every declared state")
    for state, actions in nodes.items():
        law = supplied[state]
        if (set(law) != set(actions) or any(not _finite(p) or p < 0 for p in law.values())
                or not math.isclose(math.fsum(law.values()), 1.0, abs_tol=1e-12, rel_tol=0)):
            raise ValueError("Policy probabilities must cover the full legal action set")
    return supplied


def enumerate_paths(nodes, root, policy, gamma=2.0, max_paths=100000):
    """Independent full-trajectory law, retaining action and outcome randomness."""
    validate_problem(nodes, root, gamma)
    _policy(nodes, policy)
    paths = []

    def expand(state, probability, cost, decisions):
        for action, action_probability in policy[state].items():
            if action_probability == 0:
                continue
            for branch in nodes[state][action]:
                mass = probability * action_probability * branch.probability
                steps = decisions + ((state, action),)
                charge = cost + branch.cost
                if branch.next_state is None:
                    paths.append(PathOutcome(mass, branch.terminal_utility - charge, steps))
                    if len(paths) > max_paths:
                        raise ValueError("Declared enumeration budget exhausted")
                else:
                    expand(branch.next_state, mass, charge, steps)

    expand(root, 1.0, 0.0, ())
    if not math.isclose(math.fsum(p.probability for p in paths), 1.0, abs_tol=1e-12, rel_tol=0):
        raise ArithmeticError("Enumerated trajectory probability mass was lost")
    return tuple(paths)


def policy_value(nodes, root, policy, gamma=2.0):
    paths = enumerate_paths(nodes, root, policy, gamma)
    return certainty_equivalent([p.net_return for p in paths], gamma, [p.probability for p in paths])


def brute_force_optimum(nodes, root, gamma=2.0, max_policies=100000):
    """Enumerate deterministic policies, separately from Bellman recursion."""
    validate_problem(nodes, root, gamma)
    names = sorted(nodes)
    size = math.prod(len(nodes[s]) for s in names)
    if size > max_policies:
        raise ValueError("Declared policy enumeration budget exhausted")
    best = None
    for choices in product(*(sorted(nodes[s]) for s in names)):
        policy = {s: {a: float(a == selected) for a in nodes[s]} for s, selected in zip(names, choices)}
        value = policy_value(nodes, root, policy, gamma)
        if best is None or value > best["value"]:
            best = {"value": value, "policy": dict(zip(names, choices)), "policies": size}
    return best


def softmax_policy(nodes, logits):
    if set(logits) != set(nodes):
        raise ValueError("Logits must cover all states")
    policy = {}
    for state in nodes:
        row = logits[state]
        if set(row) != set(nodes[state]) or any(not _finite(v) for v in row.values()):
            raise ValueError("Finite logits must cover all legal actions")
        peak = max(row.values())
        weights = {a: math.exp(z - peak) for a, z in row.items()}
        norm = math.fsum(weights.values())
        policy[state] = {a: p / norm for a, p in weights.items()}
    return policy


def entropic_gradient(returns, probabilities, score_vectors, gamma=2.0, return_gradients=None):
    """Exact tilted score/direct gradient for a complete finite population law.

Returns E_tilt[dR] - E_tilt[d log p]/gamma. The score must be centered
under p. Pathwise derivatives must not duplicate a node's score derivative.
"""
    certainty_equivalent(returns, gamma, probabilities)
    if gamma <= 0 or len(score_vectors) != len(returns) or not score_vectors:
        raise ValueError("A positive risk and one score vector per outcome are required")
    width = len(score_vectors[0])
    direct = return_gradients if return_gradients is not None else [(0.0,) * width] * len(returns)
    if (width == 0 or len(direct) != len(returns) or any(len(v) != width for v in (*score_vectors, *direct))
            or any(not _finite(x) for vector in (*score_vectors, *direct) for x in vector)):
        raise ValueError("Gradient vectors must be finite and dimensionally aligned")
    if any(abs(math.fsum(p * score[j] for p, score in zip(probabilities, score_vectors))) > 1e-10
           for j in range(width)):
        raise ValueError("The supplied score is not centered under the full probability law")
    logs = [math.log(p) - gamma * r if p > 0 else -math.inf for p, r in zip(probabilities, returns)]
    peak = max(logs)
    weights = [math.exp(z - peak) for z in logs]
    total = math.fsum(weights)
    weights = [w / total for w in weights]
    return tuple(math.fsum(w * (d[j] - s[j] / gamma)
                           for w, d, s in zip(weights, direct, score_vectors)) for j in range(width))


def policy_gradient(nodes, root, logits, gamma=2.0):
    """Analytic gradient of population CE with respect to every softmax logit."""
    policy = softmax_policy(nodes, logits)
    paths = enumerate_paths(nodes, root, policy, gamma)
    coordinates = tuple((s, a) for s in sorted(nodes) for a in sorted(nodes[s]))
    scores = []
    for path in paths:
        decisions = dict(path.decisions)
        scores.append(tuple(float(decisions[s] == a) - policy[s][a] if s in decisions else 0.0
                            for s, a in coordinates))
    gradient = entropic_gradient([p.net_return for p in paths], [p.probability for p in paths], scores, gamma)
    return {"value": policy_value(nodes, root, policy, gamma),
            "gradient": {s: {a: gradient[coordinates.index((s, a))] for a in sorted(nodes[s])}
                         for s in sorted(nodes)}}
