"""NDU-JAC recursive finite-model reference (action randomization outside CE).

API: Outcome(probability, reward=0, cost=0, adjustment_cost=0, duration=0,
             next_state=None); evaluate(nodes, root, policy, eta=1, rho=0);
softmax_policy(nodes, logits); policy_gradient(nodes, root, logits, eta=1, rho=0);
optimal_policy(nodes, root, eta=1, rho=0).

Nodes are state -> action -> immutable tuple[Outcome]. Terminal outcomes have
next_state=None. State names must encode all history, budget, clock and version
needed to make each declared action admissible. This explicit reference neither
infers support nor grants runtime authority. It is not the inherited trajectory
CE objective, and does not modify that historical oracle.
"""

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Outcome:
    probability: float
    reward: float = 0.0
    cost: float = 0.0
    adjustment_cost: float = 0.0
    duration: float = 0.0
    next_state: str | None = None


def _finite(x):
    return isinstance(x, (float, int)) and not isinstance(x, bool) and math.isfinite(x)


def _validate(nodes, root, eta, rho):
    if (not _finite(eta) or eta <= 0 or not _finite(rho) or rho < 0
            or not isinstance(nodes, dict) or not 1 <= len(nodes) <= 512
            or root not in nodes):
        raise ValueError("Require a bounded finite model, eta > 0, rho >= 0")
    for state, actions in nodes.items():
        if (not isinstance(state, str) or not state or not isinstance(actions, dict)
                or not actions or len(actions) > 256):
            raise ValueError("States require a bounded explicit legal action set")
        for action, law in actions.items():
            if (not isinstance(action, str) or not action or not isinstance(law, tuple)
                    or not 1 <= len(law) <= 4096):
                raise ValueError("Actions require complete immutable outcome laws")
            for o in law:
                if (not isinstance(o, Outcome)
                        or not all(_finite(x) for x in (o.probability, o.reward, o.cost,
                                                       o.adjustment_cost, o.duration))
                        or o.probability <= 0 or min(o.cost, o.adjustment_cost, o.duration) < 0
                        or o.next_state is not None and o.next_state not in nodes
                        or action.upper() == "STOP" and o.next_state is not None):
                    raise ValueError("Invalid joint outcome or nonterminal STOP")
            if not math.isclose(math.fsum(o.probability for o in law), 1.0,
                                rel_tol=0, abs_tol=1e-12):
                raise ValueError("Missing outcome mass; failures cannot be dropped")
    active, done, order = set(), set(), []

    def visit(state):
        if state in active:
            raise ValueError("Finite-horizon state must make the model acyclic")
        if state in done:
            return
        active.add(state)
        for law in nodes[state].values():
            for o in law:
                if o.next_state is not None:
                    visit(o.next_state)
        active.remove(state)
        done.add(state)
        order.append(state)

    for state in sorted(nodes):
        visit(state)
    return order


def _policy(nodes, policy):
    if not isinstance(policy, dict) or set(policy) != set(nodes):
        raise ValueError("Policy must cover all declared states")
    normalized = {}
    for state, actions in nodes.items():
        row = policy[state]
        if (not isinstance(row, dict) or set(row) != set(actions)
                or any(not _finite(p) or p < 0 for p in row.values())
                or not math.isclose(math.fsum(row.values()), 1.0, rel_tol=0, abs_tol=1e-12)):
            raise ValueError("Policy must cover exactly the legal action set")
        mass = math.fsum(row.values())
        normalized[state] = {action: probability / mass for action, probability in row.items()}
    return normalized


def softmax_policy(nodes, logits):
    """Stable independent logit rows, including actions currently very unlikely."""
    if not isinstance(logits, dict) or set(logits) != set(nodes):
        raise ValueError("Logits must cover all states")
    policy = {}
    for state, actions in nodes.items():
        row = logits[state]
        if (not isinstance(row, dict) or set(row) != set(actions)
                or any(not _finite(z) for z in row.values())):
            raise ValueError("Finite logits must cover exactly the legal action set")
        peak = max(row.values())
        weights = {a: math.exp(z - peak) for a, z in row.items()}
        norm = math.fsum(weights.values())
        policy[state] = {a: w / norm for a, w in weights.items()}
    return policy


def _action_value(law, values, eta, rho):
    returns = tuple(o.reward - o.cost - o.adjustment_cost
                    + (math.exp(-rho * o.duration) * values[o.next_state]
                       if o.next_state is not None else 0.0) for o in law)
    if not all(math.isfinite(x) for x in returns):
        raise ArithmeticError("Nonfinite complete branch return")
    # Shift by a branch return, avoiding exp(-eta*x) overflow.
    anchor = min(returns)
    mass = math.fsum(o.probability for o in law)
    probabilities = tuple(o.probability / mass for o in law)
    weights = tuple(p * math.exp(-eta * (x - anchor))
                    for p, x in zip(probabilities, returns))
    total = math.fsum(weights)
    spread = eta * (max(returns) - anchor)
    log_moment = (math.log1p(math.fsum(p * math.expm1(-eta * (x - anchor))
                                     for p, x in zip(probabilities, returns)))
                  if spread < 0.5 else math.log(total))
    q = anchor - log_moment / eta
    if not math.isfinite(q):
        raise ArithmeticError("Nonfinite conditional certainty equivalent")
    return q, tuple(w / total for w in weights)


def evaluate(nodes, root, policy, eta=1.0, rho=0.0):
    """Evaluate V=sum(pi*Q), Q=CE(R-C-kappa+exp(-rho*dt)*V_next).

    tilted_probabilities[state][action] contains P(outcome)*m(outcome), not
    m itself. This avoids dividing by rare physical outcome probabilities.
    Terminal rewards are immediate in this model; only continuation discounts.
    """
    order = _validate(nodes, root, eta, rho)
    policy = _policy(nodes, policy)
    values, action_values, tilts, advantages = {}, {}, {}, {}
    for state in order:
        action_values[state], tilts[state] = {}, {}
        for action, law in nodes[state].items():
            q, tilt = _action_value(law, values, eta, rho)
            action_values[state][action], tilts[state][action] = q, tilt
        # Center before mixing; a large common currency offset must not create
        # artificial advantage through tolerated mass error or cancellation.
        anchor = action_values[state][next(iter(nodes[state]))]
        centered = {a: q - anchor for a, q in action_values[state].items()}
        mean = math.fsum(policy[state][a] * centered[a] for a in nodes[state])
        values[state] = anchor + mean
        advantages[state] = {a: q - mean for a, q in centered.items()}
        if not math.isfinite(values[state]):
            raise ArithmeticError("Nonfinite recursive policy value")
    return {"value": values[root], "values": values, "action_values": action_values,
            "tilted_probabilities": tilts, "order": tuple(order),
            "policy": policy, "advantages": advantages}


def optimal_policy(nodes, root, eta=1.0, rho=0.0):
    """Exact Bellman optimum for this declared finite model, with stable ties."""
    order = _validate(nodes, root, eta, rho)
    values, policy, action_values = {}, {}, {}
    for state in order:
        row = {a: _action_value(nodes[state][a], values, eta, rho)[0]
               for a in sorted(nodes[state])}
        chosen = max(row, key=row.get)
        values[state], action_values[state] = row[chosen], row
        policy[state] = {a: float(a == chosen) for a in row}
    return {"value": values[root], "values": values, "action_values": action_values,
            "policy": policy}


def policy_gradient(nodes, root, logits, eta=1.0, rho=0.0):
    """Exact recursive derivative with respect to independent softmax logits.

    The source score uses occupancy w_t. Outcome risk and duration affect the
    successor occupancy only. For an autodiff surrogate, both evaluated Q and
    occupancy must be detached. Direct derivatives of transitions, prices,
    rewards or risk parameters are not covered by this fixed-model API.
    """
    policy = softmax_policy(nodes, logits)
    result = evaluate(nodes, root, policy, eta, rho)
    policy = result["policy"]
    occupancy = {s: float(s == root) for s in nodes}
    for state in reversed(result["order"]):
        for action, law in nodes[state].items():
            for o, tilted in zip(law, result["tilted_probabilities"][state][action]):
                if o.next_state is not None:
                    occupancy[o.next_state] += (occupancy[state] * policy[state][action]
                                                * tilted * math.exp(-rho * o.duration))
    gradient = {s: {a: occupancy[s] * policy[s][a]
                      * result["advantages"][s][a]
                   for a in nodes[s]} for s in nodes}
    return {**result, "policy": policy, "occupancy": occupancy, "gradient": gradient}
