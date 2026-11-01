"""Independent alpha-vector enumeration and frozen-belief sampling checks."""

import hashlib
import itertools
import json
from pathlib import Path

import numpy as np

from controller import marginalization_diagnostics, plan, plan_mc


def policy_vectors(P, emission, rewards, read_cost, horizon, budget, tick_cost):
    """Enumerate contingent policies as state-wise payoffs, without filtering."""
    groups = [rewards[:, 0:1], rewards[:, 1:2], np.empty((len(P), 0)),
              np.empty((len(P), 0))]
    if horizon == 1:
        return groups
    children = np.concatenate(policy_vectors(
        P, emission, rewards, read_cost, horizon - 1, budget, tick_cost), axis=1)
    groups[2] = -tick_cost + P @ children
    if budget:
        after_read = np.concatenate(policy_vectors(
            P, emission, rewards, read_cost, horizon - 1, budget - 1, tick_cost), axis=1)
        possible = np.flatnonzero(emission.sum(axis=0) > 0)
        vectors = []
        for choices in itertools.product(range(after_read.shape[1]), repeat=len(possible)):
            payoff = -read_cost.copy()
            for obs, child in zip(possible, choices):
                payoff += emission[:, obs] * after_read[:, child]
            vectors.append(-tick_cost + P @ payoff)
        groups[3] = np.stack(vectors, axis=1)
    return groups


def exhaustive_checks():
    P = np.array([[0.9, 0.1], [0.15, 0.85]])
    emission = np.zeros((2, 7))
    emission[:, :2] = [[0.86, 0.14], [0.18, 0.82]]
    rewards = np.array([[1.2, -0.2], [-0.1, 1.0]])
    costs = np.array([0.08, 0.14])
    grid = np.linspace(0.0, 1.0, 17)
    beliefs = np.stack([grid, 1 - grid], axis=1)
    max_error, policy_counts = 0.0, []
    for horizon in (1, 2, 3):
        for budget in (0, 1, 2):
            result = plan(beliefs, P, emission, rewards, costs,
                          horizon=horizon, budget=budget, time_cost=0.03, dt=0.4)
            groups = policy_vectors(P, emission, rewards, costs, horizon, budget, 0.012)
            expected = np.full((len(beliefs), 4), -np.inf)
            for action, vectors in enumerate(groups):
                if vectors.shape[1]:
                    expected[:, action] = (beliefs @ vectors).max(axis=1)
            np.testing.assert_allclose(result.qvalues, expected, atol=2e-14, rtol=2e-14)
            np.testing.assert_array_equal(result.action, expected.argmax(axis=1))
            np.testing.assert_allclose(result.value, expected.max(axis=1), atol=2e-14)
            finite = np.isfinite(expected)
            max_error = max(max_error, float(abs(result.qvalues[finite]-expected[finite]).max()))
            policy_counts.append({"horizon": horizon, "budget": budget,
                                  "contingent_policy_counts": [g.shape[1] for g in groups]})
    return {"cases": len(policy_counts), "beliefs_per_case": len(beliefs),
            "max_error": max_error, "policy_counts": policy_counts}, (P, emission, rewards, costs)


def edge_checks():
    rare = 1e-12
    P = np.eye(2)
    emission = np.zeros((2, 7))
    emission[:, :2] = [[1, 0], [rare, 1-rare]]
    beliefs = np.array([[rare, 1-rare], [0, 1], [1, 0]])
    rewards = np.array([[1/rare, 0], [0, 1]])
    result = plan(beliefs, P, emission, rewards, np.zeros(2),
                  horizon=2, budget=1, time_cost=0, dt=0.5)
    groups = policy_vectors(P, emission, rewards, np.zeros(2), 2, 1, 0)
    expected = np.stack([(beliefs @ vectors).max(axis=1) for vectors in groups], axis=1)
    np.testing.assert_allclose(result.qvalues, expected, atol=1e-12, rtol=1e-14)
    assert abs(result.qvalues[0, 3] - (1 + (1-rare)**2)) < 1e-12
    assert not np.isnan(result.qvalues).any()
    swap = np.array([[0., 1.], [1., 0.]])
    after_prediction = plan(np.array([[1., 0.]]), swap, emission,
        np.ones((2, 2)), np.array([0.9, 0.1]), horizon=2, budget=1, time_cost=0, dt=1)
    assert abs(after_prediction.qvalues[0, 3] - 0.9) < 1e-14
    empty = plan(np.empty((0, 2)), P, emission, rewards, np.zeros(2))
    assert empty.qvalues.shape == (0, 4)
    rejected = False
    try:
        plan(np.array([[1.1, -0.1]]), P, emission, rewards, np.zeros(2))
    except ValueError:
        rejected = True
    assert rejected
    # Deterministic observation leaves no sampling variation.
    one_obs = np.zeros((2, 7))
    one_obs[:, 6] = 1
    kwargs = dict(horizon=3, budget=2, time_cost=0.01, dt=0.3)
    exact = plan(beliefs, P, one_obs, rewards, np.zeros(2), **kwargs)
    sampled = plan_mc(beliefs, P, one_obs, rewards, np.zeros(2), **kwargs,
                       mc_samples=32, rng=np.random.default_rng(7))
    np.testing.assert_allclose(exact.qvalues, sampled.qvalues, atol=1e-12, rtol=1e-14)
    return {"rare_evidence": float(beliefs[0] @ emission[:, 0]),
        "rare_read_qvalue": float(result.qvalues[0, 3]),
        "zero_evidence_branches_skipped": True, "predicted_read_cost_used": True,
        "invalid_belief_rejected": rejected, "empty_batch_supported": True,
        "deterministic_observation_mc_matches": True}


def main():
    checks, model = exhaustive_checks()
    edge = edge_checks()
    grid = np.linspace(0.05, 0.95, 13)
    beliefs = np.stack([grid, 1-grid], axis=1)
    diagnostics = marginalization_diagnostics(beliefs, *model, horizon=3, budget=2,
        time_cost=0.03, dt=0.4, mc_samples=32, repetitions=64, seed=20261031)
    source = Path(__file__).with_name("controller.py")
    report = {"status": "independent_enumeration_checks_passed",
        "scope": "Constructed two-state fixtures, not a task confirmation dataset.",
        "controller_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "test_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "numpy": np.__version__, "exhaustive": checks, "edge_cases": edge,
        "sampling_diagnostics": diagnostics}
    target = Path(__file__).with_name("raw.json")
    target.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "max_exact_error": checks["max_error"],
        "mc_action_disagreement": diagnostics["action_disagreement_rate"],
        "mc_mean_action_regret": diagnostics["mean_exact_model_action_regret"]}))


if __name__ == "__main__":
    main()
