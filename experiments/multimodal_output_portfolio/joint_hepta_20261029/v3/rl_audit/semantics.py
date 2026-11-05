"""Bounded public-state semantic oracle, not a learned NDU algorithm.

A cost is paid at action admission, then the realized duration discounts the
continuation or terminal payoff. Risk is recursive entropic certainty equivalent
of the *joint* policy/environment draw. Action randomization is risk exposed.
"""

from dataclasses import dataclass
from decimal import Decimal, localcontext
from functools import lru_cache
from itertools import product
from types import MappingProxyType
import json
import math
import time


def _finite(x):
    return type(x) in (int, float) and math.isfinite(x)


@dataclass(frozen=True)
class Outcome:
    probability: float
    duration: float
    next_state: str | None = None
    payoff: float | None = None


@dataclass(frozen=True)
class Action:
    cost: float
    outcomes: tuple[Outcome, ...]


@dataclass(frozen=True)
class Model:
    states: dict[str, dict[str, Action]]
    root: str

    def __post_init__(self):
        if (
            not isinstance(self.states, dict)
            or not self.states
            or len(self.states) > 64
            or self.root not in self.states
        ):
            raise ValueError("Require 1..64 public states and a declared root")
        for state, actions in self.states.items():
            if not isinstance(state, str) or not state or not isinstance(actions, dict) or not 1 <= len(actions) <= 16:
                raise ValueError("Invalid state/action count")
            for name, action in actions.items():
                if (
                    not isinstance(name, str)
                    or not name
                    or not isinstance(action, Action)
                    or not _finite(action.cost)
                    or not 0 <= action.cost <= 100
                ):
                    raise ValueError("Invalid action or admission cost")
                if (
                    not isinstance(action.outcomes, tuple)
                    or not 1 <= len(action.outcomes) <= 16
                    or any(not isinstance(o, Outcome) or not _finite(o.probability) for o in action.outcomes)
                ):
                    raise ValueError("Require immutable complete outcome tuples")
                if sum(Decimal(str(o.probability)) for o in action.outcomes) != 1:
                    raise ValueError("Incomplete probability law")
                for o in action.outcomes:
                    if not 0 < o.probability <= 1 or not _finite(o.duration) or not 0 <= o.duration <= 100:
                        raise ValueError("Invalid positive probability or duration")
                    if o.next_state is None:
                        if o.payoff is None or not _finite(o.payoff) or abs(o.payoff) > 100:
                            raise ValueError("Terminal outcome requires bounded payoff")
                    elif o.next_state not in self.states or o.payoff is not None:
                        raise ValueError("Continuation cannot also pay terminal reward")
                    if name == "STOP" and (o.next_state is not None or o.duration != 0):
                        raise ValueError("STOP is immediate and terminal")
        depths, active = {}, set()

        def depth(s):
            if s in active:
                raise ValueError("Require an acyclic public-state DAG")
            if s in depths:
                return depths[s]
            active.add(s)
            children = [
                depth(o.next_state)
                for action in self.states[s].values()
                for o in action.outcomes
                if o.next_state is not None
            ]
            depths[s] = 1 + max(children, default=0)
            active.remove(s)
            if depths[s] > 8:
                raise ValueError("At most eight decisions per path")
            return depths[s]

        for s in self.states:
            depth(s)
        object.__setattr__(
            self, "states", MappingProxyType({s: MappingProxyType(dict(a)) for s, a in self.states.items()})
        )

    def coordinates(self):
        return tuple((s, a) for s, acts in self.states.items() for a in acts)


def _parameters(model, theta, eta, rate):
    if not _finite(eta) or not 0 <= eta <= 20 or not _finite(rate) or not 0 <= rate <= 10:
        raise ValueError("Require eta in [0,20] and rate in [0,10]")
    if len(theta) != len(model.coordinates()) or any(not _finite(x) or abs(x) > 30 for x in theta):
        raise ValueError("One finite logit in [-30,30] per public state/action")


def _softmax(xs):
    peak = max(xs)
    total = math.fsum(math.exp(x - peak) for x in xs)
    return tuple(math.exp(x - peak) / total for x in xs)


def certainty_equivalent(weights, values, eta):
    """Return value and tilted weights; center small exponents before log1p."""
    mean = math.fsum(p * v for p, v in zip(weights, values))
    if eta == 0:
        return mean, tuple(weights)
    y = tuple(-eta * (v - mean) for v in values)
    if max(map(abs, y)) < 0.5:
        correction = math.fsum(p * math.expm1(z) for p, z in zip(weights, y))
        value = mean - math.log1p(correction) / eta
        tilted = tuple(p * math.exp(z) / (1 + correction) for p, z in zip(weights, y))
        return value, tilted
    logs = tuple(math.log(p) - eta * v for p, v in zip(weights, values))
    peak = max(logs)
    norm = math.fsum(math.exp(x - peak) for x in logs)
    return -(peak + math.log(norm)) / eta, tuple(math.exp(x - peak) / norm for x in logs)


def evaluate(model, theta, eta=0.0, rate=0.0):
    """Analytic reverse Bellman derivative, including policy-draw risk tilt."""
    _parameters(model, theta, eta, rate)
    coords = model.coordinates()
    index = {key: i for i, key in enumerate(coords)}
    n = len(coords)

    @lru_cache(None)
    def visit(s):
        actions = model.states[s]
        probs = _softmax([theta[index[s, a]] for a in actions])
        weights, values, child_grads, labels = [], [], [], []
        for j, action in enumerate(actions.values()):
            for o in action.outcomes:
                child, grad = (o.payoff, (0.0,) * n) if o.next_state is None else visit(o.next_state)
                discount = math.exp(-rate * o.duration)
                weights.append(probs[j] * o.probability)
                values.append(-action.cost + discount * child)
                child_grads.append(tuple(discount * g for g in grad))
                labels.append(j)
        value, tilt = certainty_equivalent(weights, values, eta)
        grad = [math.fsum(p * g[k] for p, g in zip(tilt, child_grads)) for k in range(n)]
        mean = math.fsum(p * v for p, v in zip(weights, values))
        # The local term is (pi - tilted action mass)/eta. expm1 avoids
        # catastrophic subtraction in the risk-neutral limit.
        small = eta > 0 and max(abs(eta * (v - mean)) for v in values) < 0.5
        correction = math.fsum(p * math.expm1(-eta * (v - mean)) for p, v in zip(weights, values)) if small else 0.0
        for j, a in enumerate(actions):
            if eta == 0:
                local = math.fsum(w * (v - value) for w, v, label in zip(weights, values, labels) if label == j)
            elif small:
                aj = math.fsum(
                    o.probability * math.expm1(-eta * (v - mean))
                    for o, v in zip(actions[a].outcomes, [v for v, label in zip(values, labels) if label == j])
                )
                local = probs[j] * (correction - aj) / (eta * (1 + correction))
            else:
                local = (probs[j] - math.fsum(t for t, label in zip(tilt, labels) if label == j)) / eta
            grad[index[s, a]] += local
        return value, tuple(grad)

    value, gradient = visit(model.root)
    return {"value": value, "gradient": gradient}


def optimal(model, eta=0.0, rate=0.0):
    _parameters(model, (0.0,) * len(model.coordinates()), eta, rate)
    policy = {}

    @lru_cache(None)
    def visit(s):
        q = {}
        for a, action in model.states[s].items():
            vals = [
                -action.cost
                + math.exp(-rate * o.duration) * (o.payoff if o.next_state is None else visit(o.next_state))
                for o in action.outcomes
            ]
            q[a] = certainty_equivalent([o.probability for o in action.outcomes], vals, eta)[0]
        policy[s] = max(q, key=q.get)
        return q[policy[s]]

    return {"value": visit(model.root), "policy": policy}


def enumerate_trees(model, eta=0.0, rate=0.0, cap=100000):
    """Separate Decimal arithmetic; enumerate every observation-contingent tree.

    No Bellman maximization or memoization occurs inside this enumeration. A hard
    cap rejects the whole enumeration, never prunes inconvenient continuations.
    """
    _parameters(model, (0.0,) * len(model.coordinates()), eta, rate)
    if type(cap) is not int or not 1 <= cap <= 1000000:
        raise ValueError("Invalid enumeration cap")
    count = [0]
    with localcontext() as ctx:
        ctx.prec = 50
        risk, decay = Decimal(str(eta)), Decimal(str(rate))

        def trees(s):
            results = []
            for action in model.states[s].values():
                children = [
                    (Decimal(str(o.payoff)),) if o.next_state is None else trees(o.next_state) for o in action.outcomes
                ]
                for choices in product(*children):
                    count[0] += 1
                    if count[0] > cap:
                        raise ValueError("Policy-tree enumeration cap exhausted")
                    xs = [
                        -Decimal(str(action.cost)) + (-decay * Decimal(str(o.duration))).exp() * v
                        for o, v in zip(action.outcomes, choices)
                    ]
                    ps = [Decimal(str(o.probability)) for o in action.outcomes]
                    value = (
                        sum(p * x for p, x in zip(ps, xs))
                        if risk == 0
                        else -sum(p * (-risk * x).exp() for p, x in zip(ps, xs)).ln() / risk
                    )
                    results.append(value)
            return tuple(results)

        roots = trees(model.root)
        return {"value": float(max(roots)), "root_trees": len(roots), "subtrees": count[0]}


def decimal_policy_value(model, theta, eta=0.0, rate=0.0):
    """Independent uncached evaluator for high-precision derivative checks."""
    _parameters(model, tuple(float(x) for x in theta), eta, rate)
    with localcontext() as ctx:
        ctx.prec = 60
        risk, decay = Decimal(str(eta)), Decimal(str(rate))
        logits = dict(zip(model.coordinates(), (Decimal(str(x)) for x in theta)))

        def visit(s):
            actions = model.states[s]
            exps = {a: logits[s, a].exp() for a in actions}
            norm = sum(exps.values())
            terms = []
            for a, action in actions.items():
                for o in action.outcomes:
                    next_value = Decimal(str(o.payoff)) if o.next_state is None else visit(o.next_state)
                    x = -Decimal(str(action.cost)) + (-decay * Decimal(str(o.duration))).exp() * next_value
                    p = exps[a] / norm * Decimal(str(o.probability))
                    terms.append((p, x))
            return (
                sum(p * x for p, x in terms) if risk == 0 else -sum(p * (-risk * x).exp() for p, x in terms).ln() / risk
            )

        return visit(model.root)


def difference_gradient(model, theta, eta=0.0, rate=0.0):
    step = Decimal("0.00000001")
    values = []
    for k in range(len(theta)):
        plus, minus = [Decimal(str(x)) for x in theta], [Decimal(str(x)) for x in theta]
        plus[k] += step
        minus[k] -= step
        values.append(
            float(
                (decimal_policy_value(model, plus, eta, rate) - decimal_policy_value(model, minus, eta, rate))
                / (2 * step)
            )
        )
    return tuple(values)


def path_value_gradient(model, theta, eta=0.0, rate=0.0, max_paths=100000):
    """Independent complete terminal path/score calculation.

    For nonzero eta this is the static CE of the discounted total return. It equals
    recursive CE at rate=0, but is intentionally a different objective at rate>0.
    """
    _parameters(model, theta, eta, rate)
    coords = model.coordinates()
    index = {key: i for i, key in enumerate(coords)}
    if type(max_paths) is not int or not 1 <= max_paths <= 1000000:
        raise ValueError("Invalid path cap")
    records = []

    def expand(s, mass, total, discount, score):
        acts = model.states[s]
        probs = _softmax([theta[index[s, a]] for a in acts])
        for j, (a, action) in enumerate(acts.items()):
            next_score = list(score)
            for k, b in enumerate(acts):
                next_score[index[s, b]] += float(j == k) - probs[k]
            for o in action.outcomes:
                p = mass * probs[j] * o.probability
                new_total = total - discount * action.cost
                d = discount * math.exp(-rate * o.duration)
                if o.next_state is None:
                    records.append((p, new_total + d * o.payoff, tuple(next_score)))
                    if len(records) > max_paths:
                        raise ValueError("Complete path enumeration cap exhausted")
                else:
                    expand(o.next_state, p, new_total, d, next_score)

    expand(model.root, 1.0, 0.0, 1.0, (0.0,) * len(coords))
    with localcontext() as ctx:
        ctx.prec = 60
        rows = [(Decimal(str(p)), Decimal(str(v)), [Decimal(str(x)) for x in g]) for p, v, g in records]
        risk = Decimal(str(eta))
        if risk == 0:
            value = sum(p * v for p, v, _ in rows)
            grad = [sum(p * v * g[k] for p, v, g in rows) for k in range(len(coords))]
        else:
            z = sum(p * (-risk * v).exp() for p, v, _ in rows)
            value = -z.ln() / risk
            grad = [-sum(p * (-risk * v).exp() * g[k] for p, v, g in rows) / (risk * z) for k in range(len(coords))]
    return {"value": float(value), "gradient": tuple(float(x) for x in grad), "paths": len(records)}


def inherited_crosscheck(model, theta, eta=2.0):
    """Undiscounted equivalence with the previously committed Hepta oracle."""
    from experiments.multimodal_output_portfolio.joint_hepta_20261029.oracle import (
        Branch,
        policy_gradient,
        solve_risk_dp,
    )

    nodes = {
        s: {
            a: tuple(Branch(o.probability, action.cost, o.next_state, o.payoff) for o in action.outcomes)
            for a, action in acts.items()
        }
        for s, acts in model.states.items()
    }
    logits = {s: {} for s in nodes}
    for (s, a), x in zip(model.coordinates(), theta):
        logits[s][a] = x
    inherited = policy_gradient(nodes, model.root, logits, gamma=eta)
    current = evaluate(model, theta, eta)
    return {
        "eta": eta,
        "inherited_policy_value": inherited["value"],
        "value_error": abs(current["value"] - inherited["value"]),
        "gradient_error": max(
            abs(g - inherited["gradient"][s][a]) for (s, a), g in zip(model.coordinates(), current["gradient"])
        ),
        "optimal_value_error": abs(optimal(model, eta)["value"] - solve_risk_dp(nodes, model.root, gamma=eta)["value"]),
    }


def risk_scaled_value(model, theta, eta=0.0, rate=0.0):
    """Static discounted-return CE via augmented risk coordinate eta'=eta*d."""
    _parameters(model, theta, eta, rate)
    logits = dict(zip(model.coordinates(), theta))

    @lru_cache(None)
    def visit(s, risk):
        actions = model.states[s]
        probs = _softmax([logits[s, a] for a in actions])
        weights, xs = [], []
        for pa, action in zip(probs, actions.values()):
            for o in action.outcomes:
                d = math.exp(-rate * o.duration)
                child = o.payoff if o.next_state is None else visit(o.next_state, risk * d)
                weights.append(pa * o.probability)
                xs.append(-action.cost + d * child)
        return certainty_equivalent(weights, xs, risk)[0]

    return visit(model.root, eta)


def example_model():
    return Model(
        {
            "root": {
                "STOP": Action(0.0, (Outcome(1.0, 0.0, payoff=0.1),)),
                "observe": Action(0.1, (Outcome(0.5, 1.0, "warm"), Outcome(0.5, 3.0, "cold"))),
            },
            "warm": {
                "STOP": Action(0.0, (Outcome(1.0, 0.0, payoff=0.9),)),
                "work": Action(0.05, (Outcome(0.8, 1.0, payoff=1.4), Outcome(0.2, 2.0, payoff=-0.3))),
            },
            "cold": {
                "STOP": Action(0.0, (Outcome(1.0, 0.0, payoff=0.2),)),
                "reset": Action(0.2, (Outcome(1.0, 1.0, "warm"),)),
            },
        },
        "root",
    )


def counterexamples():
    duration = Model(
        {
            "root": {"slow": Action(0, (Outcome(1, 3, "two"),)), "fast": Action(0, (Outcome(1, 1, "one"),))},
            "two": {"STOP": Action(0, (Outcome(1, 0, payoff=2),))},
            "one": {"STOP": Action(0, (Outcome(1, 0, payoff=1),))},
        },
        "root",
    )
    neutral = evaluate(duration, (0, 0, 0, 0), rate=math.log(2))
    wrong_clock = Model(
        {
            s: {
                a: Action(
                    action.cost,
                    tuple(
                        Outcome(o.probability, 1 if o.next_state else o.duration, o.next_state, o.payoff)
                        for o in action.outcomes
                    ),
                )
                for a, action in actions.items()
            }
            for s, actions in duration.states.items()
        },
        "root",
    )
    fixed_step = evaluate(wrong_clock, (0, 0, 0, 0), rate=math.log(2))
    charged = Model({"root": {"work": Action(0.4, (Outcome(1, 2, payoff=1),))}}, "root")
    delayed_charge = Model({"root": {"work": Action(0, (Outcome(1, 2, payoff=0.6),))}}, "root")
    risk = Model(
        {
            "root": {
                "STOP": Action(0, (Outcome(1, 0, payoff=0.5),)),
                "risky": Action(0, (Outcome(0.5, 0, payoff=-1), Outcome(0.5, 0, payoff=3))),
            }
        },
        "root",
    )
    return {
        "duration_correlation": {
            "discount_per_unit": 0.9,
            "branches": [[0.5, 1, 0], [0.5, 3, 2]],
            "correct_expected_discounted_value": 0.5 * 0.9**1 * 0 + 0.5 * 0.9**3 * 2,
            "incorrect_product_of_expectations": (0.5 * 0.9 + 0.5 * 0.9**3) * (0.5 * 0 + 0.5 * 2),
        },
        "duration_GAE": {
            "rate": math.log(2),
            "correct_action_values": [0.25, 0.5],
            "fixed_step_action_values": [1.0, 0.5],
            "correct_gradient": neutral["gradient"][:2],
            "fixed_step_gradient": fixed_step["gradient"][:2],
            "interpretation": "gamma=0.5 instead of gamma**duration reverses the actor update even with exact continuation values; lambda=1 cannot repair the discount mismatch",
        },
        "entropic_GAE": {
            "eta": 2,
            "entropic": evaluate(risk, (0, 0), eta=2),
            "ordinary_expected_return": evaluate(risk, (0, 0)),
            "interpretation": "ordinary expected-return advantages optimize a different objective; both action randomization and environmental outcomes are risk exposed",
        },
        "upfront_cost": {
            "cost": 0.4,
            "duration": 2,
            "discount_per_unit": 0.5,
            "delivered_payoff": 1,
            "correct_value": evaluate(charged, (0,), rate=math.log(2))["value"],
            "incorrect_discounted_cost_value": evaluate(delayed_charge, (0,), rate=math.log(2))["value"],
        },
    }


def audit():
    wall, cpu = time.perf_counter(), time.process_time()
    model = example_model()
    theta = (0.3, -0.2, 0.5, -0.4, -0.1, 0.2)
    panels = []
    for eta, rate in product((0.0, 0.2, 2.0), (0.0, 0.13)):
        bellman, trees = optimal(model, eta, rate), enumerate_trees(model, eta, rate)
        actor = evaluate(model, theta, eta, rate)
        fd = difference_gradient(model, theta, eta, rate)
        path = path_value_gradient(model, theta, eta, rate)
        panels.append(
            {
                "eta": eta,
                "rate": rate,
                "optimal": bellman,
                "enumeration": trees,
                "bellman_error": abs(bellman["value"] - trees["value"]),
                "actor": actor,
                "independent_decimal_gradient": fd,
                "gradient_error": max(abs(x - y) for x, y in zip(actor["gradient"], fd)),
                "static_path": path,
                "risk_scaled_static_value": risk_scaled_value(model, theta, eta, rate),
                "path_objective_matches_recursive": eta == 0 or rate == 0,
            }
        )
    neutral = evaluate(model, theta, rate=0.13)
    limits = [
        {
            "eta": eta,
            "value_error": abs(evaluate(model, theta, eta, 0.13)["value"] - neutral["value"]),
            "gradient_error": max(
                abs(x - y) for x, y in zip(evaluate(model, theta, eta, 0.13)["gradient"], neutral["gradient"])
            ),
        }
        for eta in (1e-1, 1e-3, 1e-6, 1e-9)
    ]
    return {
        "scope": "bounded semantic audit; no learned-policy benefit or new-algorithm claim",
        "panels": panels,
        "risk_neutral_limit": limits,
        "counterexamples": counterexamples(),
        "inherited_oracle": inherited_crosscheck(model, theta),
        "cpu_seconds": time.process_time() - cpu,
        "wall_seconds": time.perf_counter() - wall,
        "numerical_algorithm": "binary64 recursive derivative versus independent Decimal central difference; complete path score where objectives coincide",
    }


if __name__ == "__main__":
    print(json.dumps(audit(), indent=2, sort_keys=True, allow_nan=False))
