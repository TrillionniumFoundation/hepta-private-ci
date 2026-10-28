"""Exact rational finite-MDP reference, independent of diffusion discretization.

The tiny fixture checks the production Bellman solver by enumerating every
finite-horizon deterministic Markov policy with exact Fraction arithmetic.
It establishes correctness on this declared finite task, not exactness of the
continuous diffusion, free boundary, or subsequent learned policies.
"""

from fractions import Fraction
from itertools import product
from types import SimpleNamespace

import numpy as np


F = Fraction
_ACTIONS = ("wait", "repair", "stop")


def fixture():
    """Three states and two decisions; all probabilities/rewards are rational."""
    return {
        "states": 3,
        "horizon": 2,
        "gamma": F(9, 10),
        "wait_transition": (
            (F(3, 4), F(1, 4), F(0)),
            (F(1, 8), F(3, 4), F(1, 8)),
            (F(0), F(1, 4), F(3, 4)),
        ),
        "wait_reward": (F(-3, 5), F(1, 5), F(4, 5)),
        "repair_transition": (F(1, 8), F(1, 4), F(5, 8)),
        "repair_reward": F(1, 10),
        "initial": (F(1, 4), F(1, 2), F(1, 4)),
        "terminal_value": (F(0), F(0), F(0)),
    }


def _validate(task):
    n = task["states"]
    if n < 1 or not 1 <= task["horizon"] <= 3:
        raise ValueError("Small positive finite task required")
    vectors = [*task["wait_transition"], task["repair_transition"], task["initial"]]
    if len(task["wait_transition"]) != n or any(len(row) != n for row in vectors):
        raise ValueError("Finite task shape mismatch")
    if any(any(x < 0 for x in row) or sum(row) != 1 for row in vectors):
        raise ValueError("Exact stochastic rows required")
    if len(task["wait_reward"]) != n or len(task["terminal_value"]) != n:
        raise ValueError("Finite reward shape mismatch")
    scalars = [
        task["gamma"],
        task["repair_reward"],
        *task["wait_reward"],
        *task["terminal_value"],
    ]
    if any(not isinstance(x, Fraction) for row in vectors for x in row):
        raise ValueError("Probabilities must use exact Fraction arithmetic")
    if any(not isinstance(x, Fraction) for x in scalars):
        raise ValueError("Rewards and discount must use exact Fraction arithmetic")
    if not 0 <= task["gamma"] <= 1:
        raise ValueError("Discount outside unit interval")


def evaluate_policy_exact(task, policy):
    """Evaluate a complete remaining-time/state policy without maximization."""
    _validate(task)
    n = task["states"]
    if len(policy) != task["horizon"] or any(len(row) != n for row in policy):
        raise ValueError("Policy must cover every remaining-time/state pair")
    value = list(task["terminal_value"])
    all_values = [tuple(value)]
    for row in policy:
        next_value = []
        for state, action in enumerate(row):
            if action == 0:
                reward = task["wait_reward"][state]
                transition = task["wait_transition"][state]
            elif action == 1:
                reward = task["repair_reward"]
                transition = task["repair_transition"]
            elif action == 2:
                next_value.append(F(0))
                continue
            else:
                raise ValueError("Unknown finite action")
            future = sum(p * v for p, v in zip(transition, value))
            next_value.append(reward + task["gamma"] * future)
        value = next_value
        all_values.append(tuple(value))
    return all_values


def enumerate_optimum(task):
    """Enumerate all deterministic Markov policies; no Bellman maximization."""
    _validate(task)
    n, horizon = task["states"], task["horizon"]
    policy_count = len(_ACTIONS) ** (n * horizon)
    if policy_count > 1_000_000:
        raise ValueError("Exact exhaustive reference exceeds declared small-task cap")
    best_by_state = [None] * n
    best_initial = None
    best_policy = None
    for choices in product(range(len(_ACTIONS)), repeat=n * horizon):
        policy = tuple(tuple(choices[k * n : (k + 1) * n]) for k in range(horizon))
        values = evaluate_policy_exact(task, policy)[-1]
        initial_value = sum(p * v for p, v in zip(task["initial"], values))
        if best_initial is None or initial_value > best_initial:
            best_initial, best_policy = initial_value, policy
        for state, value in enumerate(values):
            if best_by_state[state] is None or value > best_by_state[state]:
                best_by_state[state] = value
    return {
        "value": tuple(best_by_state),
        "initial_value": best_initial,
        "policy": best_policy,
        "policies_enumerated": policy_count,
    }


def production_fixture(task):
    """Convert exact finite primitives to the production solver's public fields."""
    _validate(task)
    n = task["states"]
    return SimpleNamespace(
        spec=SimpleNamespace(horizon=task["horizon"]),
        n_states=n,
        x=np.arange(1, n + 1, dtype=float),
        gamma=float(task["gamma"]),
        transition=np.asarray(task["wait_transition"], dtype=float),
        reward=np.asarray(task["wait_reward"], dtype=float),
        maintenance_transition=np.asarray(task["repair_transition"], dtype=float),
        maintenance_reward=float(task["repair_reward"]),
        initial_distribution=np.asarray(task["initial"], dtype=float),
    )


def verify_production_solver(solver=None):
    """Check real production DP against exact exhaustive values and policies."""
    if solver is None:
        from experiments.continuous_boundary_flow.math_model import solve_dp

        solver = solve_dp
    task = fixture()
    result = solver(production_fixture(task))
    rows = []
    max_error = 0.0
    for horizon in range(1, task["horizon"] + 1):
        subtask = dict(task, horizon=horizon)
        exact = enumerate_optimum(subtask)
        reported = np.asarray(result["value"][horizon], dtype=float)
        expected = np.asarray(exact["value"], dtype=float)
        if reported.shape != expected.shape or not np.isfinite(reported).all():
            raise ValueError("Invalid production finite values")
        error = float(np.max(np.abs(reported - expected)))
        max_error = max(max_error, error)
        if error > 2e-13:
            raise ValueError(
                "Production Bellman values disagree with exact enumeration"
            )
        q = np.stack(
            [
                result["q_keep"][horizon - 1],
                result["q_reset"][horizon - 1],
                result["q_stop"][horizon - 1],
            ],
            axis=-1,
        )
        if q.shape != (task["states"], len(_ACTIONS)) or not np.isfinite(q).all():
            raise ValueError("Invalid production action values")
        previous = (
            task["terminal_value"]
            if horizon == 1
            else enumerate_optimum(dict(task, horizon=horizon - 1))["value"]
        )
        exact_q = []
        for state in range(task["states"]):
            wait = task["wait_reward"][state] + task["gamma"] * sum(
                p * v for p, v in zip(task["wait_transition"][state], previous)
            )
            repair = task["repair_reward"] + task["gamma"] * sum(
                p * v for p, v in zip(task["repair_transition"], previous)
            )
            exact_q.append((wait, repair, F(0)))
        expected_q = np.asarray(exact_q, dtype=float)
        if not np.allclose(q, expected_q, atol=2e-13, rtol=0) or not np.allclose(
            result["q"][horizon - 1], expected_q, atol=2e-13, rtol=0
        ):
            raise ValueError(
                "Production Q values disagree with independent exact values"
            )
        policy = tuple(
            tuple(int(a) for a in np.argmax(result["q"][remaining], axis=-1))
            for remaining in range(horizon)
        )
        realized = evaluate_policy_exact(subtask, policy)[-1]
        if realized != exact["value"]:
            raise ValueError(
                "Production policy does not achieve the exact finite optimum"
            )
        rows.append(
            {
                "horizon": horizon,
                "policies_enumerated": exact["policies_enumerated"],
                "state_values_exact": [str(x) for x in exact["value"]],
                "initial_value_exact": str(exact["initial_value"]),
                "production_initial_value": float(
                    sum(float(p) * v for p, v in zip(task["initial"], reported))
                ),
                "max_abs_value_error": error,
                "production_policy_remaining_order": [list(row) for row in policy],
            }
        )
    initial_exact = enumerate_optimum(task)["initial_value"]
    if abs(float(result["initial_value"]) - float(initial_exact)) > 2e-13:
        raise ValueError("Production initial value is inconsistent with exact optimum")
    return {
        "schema": "hepta.continuous-boundary-policy.exact-finite-dp.v1",
        "scope": "three-state rational finite MDP; exhaustive deterministic Markov policies",
        "continuous_diffusion_exactness_claimed": False,
        "state_count": task["states"],
        "horizon": task["horizon"],
        "actions": list(_ACTIONS),
        "arithmetic": "fractions.Fraction for independent policy evaluation",
        "max_abs_value_error": max_error,
        "rows": rows,
        "passed": True,
    }
