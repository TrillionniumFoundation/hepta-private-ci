"""Exact masked softmax policy gradients for the finite nested-risk profile."""

from functools import lru_cache
import math
import numpy as np

from .core import certainty_equivalent, optimal


class SoftmaxPolicy:
    """Tabular policy: full state observation, no oracle values during training."""

    def __init__(self, env, seed=0):
        self.env = env
        states = set()

        def collect(state):
            if state in states:
                return
            states.add(state)
            for action in env.actions(state):
                if action != "stop":
                    for _, successor in env.transitions(state, action):
                        collect(successor)

        collect(env.initial)
        self.states = sorted(
            states,
            key=lambda s: (s.elapsed, s.budget, s.quality, s.preference, s.verified),
        )
        self.rows = {state: i for i, state in enumerate(self.states)}
        self.actions = env.action_names
        self.theta = np.random.default_rng(seed).normal(
            0, 0.03, (len(states), len(self.actions))
        )

    def __call__(self, state):
        legal = self.env.actions(state)
        indices = [self.actions.index(a) for a in legal]
        logits = self.theta[self.rows[state], indices]
        weights = np.exp(logits - logits.max())
        weights /= weights.sum()
        return dict(zip(legal, weights.tolist()))

    def greedy(self, state):
        probabilities = self(state)
        return max(probabilities, key=probabilities.get)


def policy_value_gradient(policy):
    """Reverse-mode derivative including risk tilt and action probability terms.

    At eta>0, tilted branch weight w_j = p_j exp(-eta X_j)/Z.
    dU = sum_j w_j dX_j - sum_j w_j dlog(pi(a_j))/eta.
    At eta=0 use sum_j p_j[dX_j + X_j dlog(pi(a_j))].
    Transition probabilities and exogenous preferences are fixed in this profile.
    """
    env = policy.env
    rows = {}

    @lru_cache(maxsize=None)
    def visit(state):
        entries = []
        for action, pi in policy(state).items():
            # The forward certainty equivalent drops zero-mass branches. Use
            # the same support here; saturated softmax probabilities are not
            # replaced with a probability floor.
            if pi == 0:
                continue
            index = policy.actions.index(action)
            if action == "stop":
                entries.append((pi, env.terminal_value(state), None, 0.0, index))
            else:
                cost, duration = env.cost_duration(action)
                discount = env.config.discount**duration
                for probability, successor in env.transitions(state, action):
                    joint_probability = pi * probability
                    if joint_probability == 0:
                        continue
                    entries.append(
                        (
                            joint_probability,
                            -env.config.cost_weight * cost
                            + discount * visit(successor),
                            successor,
                            discount,
                            index,
                        )
                    )
        probabilities = np.array([entry[0] for entry in entries])
        returns = np.array([entry[1] for entry in entries])
        value = certainty_equivalent(returns, probabilities, env.config.risk)
        if env.config.risk == 0:
            tilted = probabilities
        else:
            # Log normalization keeps rare supported branches representable
            # until the relative weights are formed. A zero-mass low return
            # must never supply the exponential shift.
            log_weights = np.log(probabilities) - env.config.risk * (
                returns - returns.min()
            )
            log_weights -= log_weights.max()
            tilted = np.exp(log_weights)
            tilted /= tilted.sum()
        rows[state] = (entries, tilted, value)
        return value

    value = visit(env.initial)
    gradient = np.zeros_like(policy.theta)
    adjoints = {env.initial: 1.0}
    for state in policy.states:
        multiplier = adjoints.get(state, 0.0)
        if multiplier == 0:
            continue
        entries, tilted, local_value = rows[state]
        pis = policy(state)
        coefficients = np.zeros(len(policy.actions))
        for entry, weight in zip(entries, tilted):
            probability, outcome, successor, discount, index = entry
            if env.config.risk == 0:
                coefficients[index] += probability * (outcome - local_value)
            else:
                coefficients[index] -= weight / env.config.risk
            if successor is not None:
                adjoints[successor] = (
                    adjoints.get(successor, 0.0) + multiplier * weight * discount
                )
        # Avoid subtraction of O(1/eta) terms when risk is near zero.
        if 0 < env.config.risk < 1e-6:
            reference = min(entry[1] for entry in entries)
            deltas = np.array(
                [math.expm1(-env.config.risk * (e[1] - reference)) for e in entries]
            )
            mean_delta = sum(e[0] * d for e, d in zip(entries, deltas))
            for action, pi in pis.items():
                index = policy.actions.index(action)
                action_delta_mass = sum(
                    e[0] * d for e, d in zip(entries, deltas) if e[4] == index
                )
                # Algebraically cancel division by pi before evaluating; pi
                # can be exactly zero after softmax underflow.
                gradient[policy.rows[state], index] += (
                    multiplier
                    * (pi * mean_delta - action_delta_mass)
                    / (env.config.risk * (1 + mean_delta))
                )
        else:
            # dlog softmax(a)/dz_b = 1[a=b] - pi(b).
            total = coefficients.sum()
            for action, pi in pis.items():
                index = policy.actions.index(action)
                gradient[policy.rows[state], index] += multiplier * (
                    coefficients[index] - pi * total
                )
    return value, gradient


def check_gradient(policy, epsilon=1e-5, max_coordinates=24):
    value, derivative = policy_value_gradient(policy)
    legal_coordinates = [
        (policy.rows[s], policy.actions.index(a))
        for s in policy.states
        for a in policy.env.actions(s)
    ]
    # Exercise high-signal coordinates plus state-spread coordinates deterministically.
    order = sorted(legal_coordinates, key=lambda ij: abs(derivative[ij]), reverse=True)
    chosen = order[: max_coordinates // 2]
    stride = max(1, len(legal_coordinates) // max(1, max_coordinates // 2))
    chosen.extend(legal_coordinates[::stride][: max_coordinates - len(chosen)])
    errors = []
    for ij in dict.fromkeys(chosen):
        original = policy.theta[ij]
        policy.theta[ij] = original + epsilon
        plus = policy_value_gradient(policy)[0]
        policy.theta[ij] = original - epsilon
        minus = policy_value_gradient(policy)[0]
        policy.theta[ij] = original
        numerical = (plus - minus) / (2 * epsilon)
        errors.append(abs(numerical - derivative[ij]))
    return {
        "value": value,
        "checked_coordinates": len(errors),
        "max_absolute_error": float(max(errors, default=0.0)),
        "epsilon": epsilon,
    }


def train_policy(env, seed=0, steps=120, learning_rate=0.15):
    """Exact model-based policy-gradient Adam; training cost is separately reported.

    This is a tabular control experiment, not a neural actor-critic or model
    quality result. No DP target or best-action table is supplied to training.
    """
    if (
        type(steps) is not int
        or steps < 0
        or not math.isfinite(learning_rate)
        or learning_rate <= 0
    ):
        raise ValueError("invalid training configuration")
    policy = SoftmaxPolicy(env, seed)
    initial_value = policy_value_gradient(policy)[0]
    moment, variance = np.zeros_like(policy.theta), np.zeros_like(policy.theta)
    for step in range(1, steps + 1):
        _, gradient = policy_value_gradient(policy)
        moment = 0.9 * moment + 0.1 * gradient
        variance = 0.999 * variance + 0.001 * gradient * gradient
        update = (moment / (1 - 0.9**step)) / (
            np.sqrt(variance / (1 - 0.999**step)) + 1e-8
        )
        policy.theta += learning_rate * update
    learned = policy_value_gradient(policy)[0]
    optimum = optimal(env)[0]
    return policy, {
        "seed": seed,
        "steps": steps,
        "initial_value": initial_value,
        "learned_value": learned,
        "optimal_value": optimum,
        "optimality_gap": optimum - learned,
        "trainable_parameters": int(policy.theta.size),
        "reachable_states": len(policy.states),
    }
