"""Finite, observable research environment for a registered NDU special case.

Profile ``nested-entropic-portfolio-v1`` instantiates the general R_J recursion
in NDU_FBSDE_SPEC section 3, not its stochastic FBSDE numerical solver. Risk is
applied to the joint action/outcome lottery, including policy randomization.
For eta > 0, R(X) = -log E[exp(-eta X)] / eta; eta=0 is expectation.
X = -cost_weight * actual_cost + discount**actual_duration * U_next.
The objective, legality and external success predicate are immutable per run.
"""

from dataclasses import dataclass
from functools import lru_cache
from itertools import product
import math

import numpy as np

PROFILE = "nested-entropic-portfolio-v1"


@dataclass(frozen=True)
class Config:
    branches: int = 2
    budget: int = 6
    horizon: int = 7
    risk: float = 0.25
    discount: float = 0.97
    cost_weight: float = 0.08
    interaction: float = 0.6
    dynamic_preferences: bool = True
    preference_flip: float = 0.2
    costs: tuple = ()
    durations: tuple = ()
    success_probabilities: tuple = ()

    def __post_init__(self):
        if self.branches not in (2, 3):
            raise ValueError("two or three branches required")
        for name, default in (
            ("costs", (1,) * self.branches),
            ("durations", (1, 2, 1)[: self.branches]),
            ("success_probabilities", (0.68, 0.55, 0.62)[: self.branches]),
        ):
            if not getattr(self, name):
                object.__setattr__(self, name, default)
            if len(getattr(self, name)) != self.branches:
                raise ValueError(f"{name} dimension mismatch")
        for v in (self.budget, self.horizon, *self.costs, *self.durations):
            if type(v) is not int or v <= 0:
                raise ValueError("resources and durations must be positive integers")
        numbers = (
            self.risk,
            self.discount,
            self.cost_weight,
            self.interaction,
            self.preference_flip,
            *self.success_probabilities,
        )
        if not all(math.isfinite(v) for v in numbers):
            raise ValueError("nonfinite configuration")
        if self.risk < 0 or self.cost_weight < 0 or self.interaction < 0:
            raise ValueError("negative risk, cost or interaction")
        if not 0 < self.discount <= 1 or not 0 <= self.preference_flip <= 1:
            raise ValueError("invalid discount or preference probability")
        if not all(0 <= p <= 1 for p in self.success_probabilities):
            raise ValueError("invalid outcome probability")
        if sum(self.costs) > self.budget or sum(self.durations) > self.horizon:
            raise ValueError("mandatory deliveries infeasible at start")


@dataclass(frozen=True)
class State:
    quality: tuple
    preference: int
    budget: int
    elapsed: int
    verified: bool = False


class Environment:
    """Fully observed toy outcomes; quality labels are not real content scores."""

    def __init__(self, config=Config()):
        self.config = config
        self.initial = State((0,) * config.branches, 0, config.budget, 0)
        self.action_names = tuple(f"generate_{i}" for i in range(config.branches)) + (
            "verify",
            "stop",
        )

    def cost_duration(self, action):
        if action == "stop":
            return 0, 0
        if action == "verify":
            return 1, 1
        if action not in self.action_names:
            raise ValueError("unknown action")
        i = int(action.rsplit("_", 1)[1])
        return self.config.costs[i], self.config.durations[i]

    @lru_cache(maxsize=None)
    def actions(self, state):
        """Reserve enough resource/time to deliver every still-missing branch."""
        if (
            len(state.quality) != self.config.branches
            or any(type(q) is not int or q not in (0, 1, 2) for q in state.quality)
            or type(state.preference) is not int
            or state.preference not in (0, 1)
            or type(state.budget) is not int
            or not 0 <= state.budget <= self.config.budget
            or type(state.elapsed) is not int
            or not 0 <= state.elapsed <= self.config.horizon
            or type(state.verified) is not bool
            or (state.verified and not all(state.quality))
        ):
            raise ValueError("invalid finite control state")
        result = []
        for action in self.action_names:
            if action == "stop":
                if all(state.quality):
                    result.append(action)
                continue
            if action == "verify":
                if not all(state.quality) or state.verified:
                    continue
                missing = [i for i, q in enumerate(state.quality) if q == 0]
            else:
                branch = int(action.rsplit("_", 1)[1])
                if state.quality[branch] >= 2:
                    continue
                missing = [
                    i for i, q in enumerate(state.quality) if q == 0 and i != branch
                ]
            cost, duration = self.cost_duration(action)
            reserve_cost = sum(self.config.costs[i] for i in missing)
            reserve_time = sum(self.config.durations[i] for i in missing)
            if (
                cost + reserve_cost <= state.budget
                and state.elapsed + duration + reserve_time <= self.config.horizon
            ):
                result.append(action)
        return tuple(result)

    @lru_cache(maxsize=None)
    def transitions(self, state, action):
        """Exact probabilities over quality and duration-aware exogenous preference."""
        if action not in self.actions(state) or action == "stop":
            raise ValueError("transition requires a legal non-stop action")
        cost, duration = self.cost_duration(action)
        flip = (
            0.5 * (1 - (1 - 2 * self.config.preference_flip) ** duration)
            if self.config.dynamic_preferences
            else 0.0
        )
        quality_outcomes = [(1.0, state.quality)]
        if action != "verify":
            i = int(action.rsplit("_", 1)[1])
            p = self.config.success_probabilities[i]
            quality_outcomes = []
            for success, probability in ((True, p), (False, 1 - p)):
                q = list(state.quality)
                q[i] = 2 if success else max(1, q[i])
                quality_outcomes.append((probability, tuple(q)))
        outcomes = {}
        for (p, q), (change, pp) in product(
            quality_outcomes, ((0, 1 - flip), (1, flip))
        ):
            successor = State(
                q,
                state.preference ^ change,
                state.budget - cost,
                state.elapsed + duration,
                action == "verify",
            )
            outcomes[successor] = outcomes.get(successor, 0.0) + p * pp
        return tuple((p, s) for s, p in outcomes.items() if p > 0)

    def terminal_value(self, state):
        if not all(state.quality):
            raise ValueError("terminal missing a required delivery")
        q = np.asarray(state.quality, dtype=float) / 2
        weights = np.ones(self.config.branches)
        weights[0 if state.preference == 0 else -1] += 0.6
        quality = float(weights @ q / weights.sum())
        joint = (
            self.config.interaction * float(q.min()) * (1 if state.verified else 0.5)
        )
        return quality + joint

    def external_metrics(self, state):
        """Fixed task outcome, independent of preference/risk/internal value."""
        return {
            "joint_success": all(q == 2 for q in state.quality) and state.verified,
            "weakest_quality": min(state.quality) / 2,
            "missing_deliveries": sum(q == 0 for q in state.quality),
            "unchecked_cross_modal": not state.verified,
            "per_modality_quality": [q / 2 for q in state.quality],
        }


def certainty_equivalent(values, probabilities, risk):
    """Stable monotone certainty equivalent, with exact risk-neutral limit."""
    x, p = np.asarray(values, float), np.asarray(probabilities, float)
    if x.shape != p.shape or x.ndim != 1 or len(x) == 0:
        raise ValueError("invalid lottery shape")
    if not np.all(np.isfinite(x)) or not np.all(np.isfinite(p)) or np.any(p < 0):
        raise ValueError("invalid lottery values")
    if (
        not math.isfinite(risk)
        or risk < 0
        or not np.isclose(p.sum(), 1, atol=1e-12, rtol=0)
    ):
        raise ValueError("invalid risk or total probability")
    x, p = x[p > 0], p[p > 0]
    if risk == 0:
        return float(p @ x)
    minimum = float(x.min())
    scaled = -risk * (x - minimum)
    delta = float(p @ np.expm1(scaled))
    log_mean = (
        math.log1p(delta) if delta > -0.5 else math.log(float(p @ np.exp(scaled)))
    )
    return minimum - log_mean / risk


def optimal(env, start=None):
    """Backward Bellman optimum; stochastic action mixing cannot improve this CE."""
    values, policy = {}, {}

    def visit(state):
        if state in values:
            return values[state]
        choices = {}
        for action in env.actions(state):
            if action == "stop":
                choices[action] = env.terminal_value(state)
            else:
                cost, duration = env.cost_duration(action)
                pairs = env.transitions(state, action)
                future = [
                    -env.config.cost_weight * cost
                    + env.config.discount**duration * visit(s)
                    for _, s in pairs
                ]
                choices[action] = certainty_equivalent(
                    future, [p for p, _ in pairs], env.config.risk
                )
        if not choices:
            raise ValueError("unreachable infeasible state")
        policy[state] = max(choices, key=choices.get)
        values[state] = choices[policy[state]]
        return values[state]

    value = visit(start or env.initial)
    return value, policy, values


def evaluate_policy(env, policy, start=None):
    """Evaluate deterministic or probability-mapping policies under the same R_J."""

    @lru_cache(maxsize=None)
    def visit(state):
        choice = policy(state) if callable(policy) else policy[state]
        weights = {choice: 1.0} if isinstance(choice, str) else choice
        if set(weights) - set(env.actions(state)):
            raise ValueError("policy assigns probability to an illegal action")
        if any(not math.isfinite(p) or p < 0 for p in weights.values()):
            raise ValueError("invalid policy probability")
        if not math.isclose(sum(weights.values()), 1.0, abs_tol=1e-12, rel_tol=0):
            raise ValueError("policy probabilities must sum to one")
        values, probabilities = [], []
        for action, weight in weights.items():
            if weight == 0:
                continue
            if action == "stop":
                values.append(env.terminal_value(state))
                probabilities.append(weight)
                continue
            cost, duration = env.cost_duration(action)
            for probability, successor in env.transitions(state, action):
                values.append(
                    -env.config.cost_weight * cost
                    + env.config.discount**duration * visit(successor)
                )
                probabilities.append(weight * probability)
        return certainty_equivalent(values, probabilities, env.config.risk)

    return visit(start or env.initial)


def enumerate_policy_trees(env, start=None, limit=100000):
    """Independent full contingent-plan enumeration, deliberately no Bellman max.

    This includes history-dependent deterministic plans and recomputes repeated
    states. Tiny configurations only; the limit fails rather than pruning trees.
    """

    def enumerate_at(state):
        results = []
        for action in env.actions(state):
            if action == "stop":
                results.append(env.terminal_value(state))
                continue
            outcomes = env.transitions(state, action)
            child_values = [enumerate_at(s) for _, s in outcomes]
            combinations = math.prod(map(len, child_values))
            if len(results) + combinations > limit:
                raise ValueError("policy tree enumeration limit exceeded")
            cost, duration = env.cost_duration(action)
            for continuation in product(*child_values):
                returns = [
                    -env.config.cost_weight * cost
                    + env.config.discount**duration * value
                    for value in continuation
                ]
                if env.config.risk == 0:
                    value = math.fsum(p * x for (p, _), x in zip(outcomes, returns))
                else:
                    value = (
                        -math.log(
                            math.fsum(
                                p * math.exp(-env.config.risk * x)
                                for (p, _), x in zip(outcomes, returns)
                            )
                        )
                        / env.config.risk
                    )
                results.append(value)
        if len(results) > limit:
            raise ValueError("policy tree enumeration limit exceeded")
        return results

    values = enumerate_at(start or env.initial)
    return max(values), len(values)


def rollout(env, policy, seed=0, start=None):
    rng = np.random.default_rng(seed)
    state, trace = start or env.initial, []
    while True:
        choice = policy(state) if callable(policy) else policy[state]
        if isinstance(choice, str):
            action = choice
        else:
            names = tuple(choice)
            action = names[int(rng.choice(len(names), p=[choice[a] for a in names]))]
        if action not in env.actions(state):
            raise ValueError("rollout illegal action")
        if action == "stop":
            return state, trace
        outcomes = env.transitions(state, action)
        successor = outcomes[
            int(rng.choice(len(outcomes), p=[p for p, _ in outcomes]))
        ][1]
        trace.append(
            {
                "action": action,
                "cost": state.budget - successor.budget,
                "duration": successor.elapsed - state.elapsed,
            }
        )
        state = successor
