"""Independent finite-MDP checks of the V5 conditional improvement claims.

Only NumPy and the standard library are used. No neural data, production
controller, guard implementation, or remote service is imported. Passing
these examples does not certify the empirical OOF gate or neural efficacy.
"""

import json
import time
import unittest

import numpy as np


DIAGNOSTICS = {}


def reference_values(transition, reward, terminal, policy):
    """Backward conditional expectation for a fully specified finite MDP."""
    horizon, states, _, _ = transition.shape
    values = np.empty((horizon + 1, states))
    q_values = np.empty(reward.shape)
    values[-1] = terminal
    for step in range(horizon - 1, -1, -1):
        q_values[step] = reward[step] + np.einsum(
            "saj,j->sa", transition[step], values[step + 1]
        )
        values[step] = q_values[step, np.arange(states), policy[step]]
    return values, q_values


def forward_value(transition, reward, terminal, policy, start, state):
    """Independent forward occupancy evaluation; no backward-value reuse."""
    states = transition.shape[1]
    occupancy = np.eye(states)[state]
    total = 0.0
    for step in range(start, len(policy)):
        actions = policy[step]
        total += float(occupancy @ reward[step, np.arange(states), actions])
        occupancy = occupancy @ transition[step, np.arange(states), actions]
    return total + float(occupancy @ terminal)


def interval_gate(estimate, error, reference, feasible):
    """Sufficient interval rule; callers must justify the error premise."""
    estimate, error = np.asarray(estimate), np.asarray(error)
    if (estimate.shape != error.shape or feasible.shape != estimate.shape
            or reference.shape != estimate.shape[:-1]
            or not np.isfinite(estimate).all() or not np.isfinite(error).all()
            or (error < 0).any()):
        raise ValueError("Missing or invalid actionwise error premise")
    if not np.take_along_axis(feasible, reference[..., None], axis=-1).all():
        raise ValueError("Reference action must remain feasible")
    best = np.argmax(np.where(feasible, estimate, -np.inf), axis=-1)
    lower = np.take_along_axis(estimate - error, best[..., None], axis=-1)[..., 0]
    upper_ref = np.take_along_axis(
        estimate + error, reference[..., None], axis=-1
    )[..., 0]
    return np.where(lower > upper_ref, best, reference)


def random_mdp(seed):
    rng = np.random.default_rng(seed)
    transition = rng.dirichlet(np.ones(3), size=(3, 3, 3))
    reward = rng.normal(size=(3, 3, 3))
    terminal = rng.normal(size=3)
    reference = rng.integers(0, 3, size=(3, 3))
    return rng, transition, reward, terminal, reference


class PolicyImprovementContracts(unittest.TestCase):
    def test_exact_reference_greedy_improves_without_equal_deployed_q(self):
        strict = 0
        distinct_q = 0
        minimum_advantage = np.inf
        for seed in range(24):
            _, trans, reward, terminal, ref = random_mdp(seed)
            baseline, q_ref = reference_values(trans, reward, terminal, ref)
            greedy = q_ref.argmax(axis=-1)
            _, q_new = reference_values(trans, reward, terminal, greedy)
            distinct_q += int(np.max(np.abs(q_new - q_ref)) > 1e-8)
            for step in range(3):
                for state in range(3):
                    gain = forward_value(trans, reward, terminal, greedy, step, state) - baseline[step, state]
                    self.assertGreaterEqual(gain, -1e-12)
                    strict += int(gain > 1e-8)
                    minimum_advantage = min(minimum_advantage, gain)
        self.assertGreater(strict, 0)
        self.assertGreater(distinct_q, 0)
        DIAGNOSTICS["exact_greedy"] = dict(
            mdps=24, state_time_checks=216, strict_improvements=strict,
            cases_with_different_deployed_q=distinct_q,
            minimum_advantage=float(minimum_advantage),
        )

    def test_interval_gate_and_performance_difference_on_new_occupancy(self):
        switches = 0
        rejected_nominal_choices = 0
        maximum_identity_error = 0.0
        for seed in range(24, 48):
            rng, trans, reward, terminal, ref = random_mdp(seed)
            baseline, q_ref = reference_values(trans, reward, terminal, ref)
            eps = rng.uniform(0.05, 0.8, size=q_ref.shape)
            estimate = q_ref + eps * rng.uniform(-1, 1, size=q_ref.shape)
            policy = interval_gate(estimate, eps, ref, np.ones_like(q_ref, dtype=bool))
            switches += int((policy != ref).sum())
            rejected_nominal_choices += int(((estimate.argmax(-1) != ref) & (policy == ref)).sum())
            for step in range(3):
                for state in range(3):
                    value = forward_value(trans, reward, terminal, policy, step, state)
                    self.assertGreaterEqual(value - baseline[step, state], -1e-12)
                    occupancy = np.eye(3)[state]
                    advantage_sum = 0.0
                    for k in range(step, 3):
                        actions = policy[k]
                        advantage = q_ref[k, np.arange(3), actions] - baseline[k]
                        advantage_sum += float(occupancy @ advantage)
                        occupancy = occupancy @ trans[k, np.arange(3), actions]
                    error = abs(value - baseline[step, state] - advantage_sum)
                    self.assertLess(error, 2e-12)
                    maximum_identity_error = max(maximum_identity_error, error)
        self.assertGreater(switches, 0)
        self.assertGreater(rejected_nominal_choices, 0)
        DIAGNOSTICS["interval_gate"] = dict(
            mdps=24, state_time_checks=216, switches=switches,
            nominal_choices_rejected=rejected_nominal_choices,
            maximum_performance_difference_error=maximum_identity_error,
        )

    def test_approximate_greedy_has_accumulated_error_bound(self):
        for seed in range(48, 60):
            rng, trans, reward, terminal, ref = random_mdp(seed)
            baseline, q_ref = reference_values(trans, reward, terminal, ref)
            eps = np.array([0.7, 0.5, 0.3])
            estimate = q_ref + eps[:, None, None] * rng.uniform(-1, 1, size=q_ref.shape)
            greedy = estimate.argmax(-1)
            for step in range(3):
                for state in range(3):
                    value = forward_value(trans, reward, terminal, greedy, step, state)
                    self.assertGreaterEqual(value - baseline[step, state], -2 * eps[step:].sum() - 1e-12)

    def test_gate_respects_feasibility_and_rejects_invalid_error_budgets(self):
        estimate = np.array([[[0.0, 100.0], [0.0, 2.0]]])
        errors = np.zeros_like(estimate)
        ref = np.array([[0, 0]])
        feasible = np.array([[[True, False], [True, True]]])
        np.testing.assert_array_equal(interval_gate(estimate, errors, ref, feasible), [[0, 1]])
        for bad in (np.full_like(errors, np.nan), np.full_like(errors, -0.1)):
            with self.assertRaises(ValueError):
                interval_gate(estimate, bad, ref, feasible)
        with self.assertRaises(ValueError):
            interval_gate(estimate, errors, np.array([[1, 0]]), feasible)
        np.testing.assert_array_equal(
            interval_gate(np.zeros_like(estimate), errors, np.array([[1, 1]]), np.ones_like(feasible)),
            [[1, 1]],
        )

    def test_ignoring_guard_can_reverse_an_exact_model_recommendation(self):
        # Rejected attempts restore the low state but consume a time slot and
        # cost. An unguarded model incorrectly predicts reaching a valuable state.
        true_trans = np.broadcast_to(np.eye(2)[:, None, :], (2, 2, 2, 2)).copy()
        nominal = true_trans.copy()
        nominal[:, 0, 1] = [0, 1]
        reward = np.zeros((2, 2, 2))
        reward[:, 0, 1] = -0.25
        terminal = np.array([0.0, 2.0])
        ref = np.zeros((2, 2), dtype=int)
        _, wrong_q = reference_values(nominal, reward, terminal, ref)
        _, true_q = reference_values(true_trans, reward, terminal, ref)
        wrong = wrong_q.argmax(-1)
        baseline = forward_value(true_trans, reward, terminal, ref, 0, 0)
        deployed = forward_value(true_trans, reward, terminal, wrong, 0, 0)
        correct = forward_value(true_trans, reward, terminal, true_q.argmax(-1), 0, 0)
        self.assertLess(deployed, baseline)
        self.assertEqual(correct, baseline)
        DIAGNOSTICS["guard_counterexample"] = dict(reference=baseline, wrong_model=deployed, guard_aware=correct)

    def test_hidden_state_alias_changes_occupancy_and_breaks_improvement(self):
        # Initial state 0 chooses between hidden states L=1 and R=2. At t=1
        # the observer aliases L/R. A predictor exact on reference occupancy L
        # chooses the same risky action in newly visited R, losing nine units.
        trans = np.zeros((2, 3, 2, 3))
        trans[0, :, 0, 1] = 1.0
        trans[0, :, 1, 2] = 1.0
        trans[1] = np.broadcast_to(np.eye(3)[:, None, :], (3, 2, 3))
        reward = np.zeros((2, 3, 2))
        reward[0, 0, 1] = 2.0
        reward[1, 1, 1] = 1.0
        reward[1, 2, 1] = -9.0
        terminal = np.zeros(3)
        ref = np.zeros((2, 3), dtype=int)
        _, q_ref = reference_values(trans, reward, terminal, ref)
        exact = q_ref.argmax(-1)
        aliased = exact.copy()
        aliased[1, 2] = aliased[1, 1]
        baseline = forward_value(trans, reward, terminal, ref, 0, 0)
        exact_value = forward_value(trans, reward, terminal, exact, 0, 0)
        aliased_value = forward_value(trans, reward, terminal, aliased, 0, 0)
        self.assertGreater(exact_value, baseline)
        self.assertLess(aliased_value, baseline)
        DIAGNOSTICS["hidden_state_counterexample"] = dict(
            reference=baseline, complete_state=exact_value, aliased_state=aliased_value,
            initial_law_changed=False, reference_occupancy_prediction_error=0.0,
        )

    def test_one_exact_tail_and_zero_old_residual_are_not_expected_q_bounds(self):
        # Safe action returns zero; a risky action returns +2 with probability
        # 0.1 and -1 otherwise. A perfectly executed lucky path is not its mean.
        risky_outcomes = np.array([2.0, -1.0])
        expected = float(np.array([0.1, 0.9]) @ risky_outcomes)
        self.assertGreater(risky_outcomes[0], 0)
        self.assertLess(expected, 0)
        # Finite OOF residuals can all be zero while a new state's advantage
        # has the wrong sign. No data-free extrapolation certificate follows.
        old_estimate = np.array([[0.0, 0.2], [0.0, 0.1]])
        old_realization = old_estimate.copy()
        threshold = float(np.max(np.abs(old_estimate - old_realization)))
        new_estimate, new_truth = np.array([0.0, 1.0]), np.array([0.0, -1.0])
        chosen = int(new_estimate.argmax()) if new_estimate.max() - new_estimate[0] > threshold else 0
        self.assertLess(new_truth[chosen], new_truth[0])
        DIAGNOSTICS["tail_and_residual_counterexamples"] = dict(
            lucky_tail=float(risky_outcomes[0]), expected_risky_return=expected,
            old_residual_threshold=threshold, new_selected_true_advantage=float(new_truth[chosen]),
        )

    def test_mismatched_tail_can_lose_to_fallback_even_with_exact_q(self):
        # Label reference uses action 0. The ordinary fallback uses action 1,
        # whose strong later behavior is not represented by that Q_ref tail.
        trans = np.zeros((2, 3, 2, 3))
        trans[0, :, 0, 2] = 1.0
        trans[0, :, 1, 1] = 1.0
        trans[1] = np.broadcast_to(np.eye(3)[:, None, :], (3, 2, 3))
        reward = np.zeros((2, 3, 2))
        reward[0, 0, 0] = 2.0
        reward[1, 1, 1] = 10.0
        terminal = np.zeros(3)
        reference = np.zeros((2, 3), dtype=int)
        baseline = np.ones((2, 3), dtype=int)
        _, q_ref = reference_values(trans, reward, terminal, reference)
        policy = interval_gate(q_ref, np.zeros_like(q_ref), baseline, np.ones_like(q_ref, dtype=bool))
        ordinary_value = forward_value(trans, reward, terminal, baseline, 0, 0)
        gated_value = forward_value(trans, reward, terminal, policy, 0, 0)
        reference_value = forward_value(trans, reward, terminal, reference, 0, 0)
        self.assertLess(gated_value, ordinary_value)
        self.assertGreaterEqual(gated_value, reference_value)
        DIAGNOSTICS["mismatched_tail_counterexample"] = dict(
            label_reference=reference_value, ordinary_baseline=ordinary_value,
            exact_q_reference_gate=gated_value, q_estimation_error=0.0,
        )


if __name__ == "__main__":
    started = time.perf_counter()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(PolicyImprovementContracts)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(json.dumps({
        "schema": "hepta.field-bridge.v5.policy-improvement-contracts.1",
        "passed": result.wasSuccessful(), "tests_run": result.testsRun,
        "wall_seconds": time.perf_counter() - started,
        "scope": "finite-MDP mathematical contracts; no empirical neural certificate",
        "diagnostics": DIAGNOSTICS,
    }, sort_keys=True, indent=2))
    raise SystemExit(0 if result.wasSuccessful() else 1)
