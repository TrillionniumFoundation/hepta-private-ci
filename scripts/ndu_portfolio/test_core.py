"""Numerical and invariant tests; no real generation efficacy is inferred."""

from dataclasses import replace
import unittest
import numpy as np

from .core import Config, Environment, State, certainty_equivalent
from .core import enumerate_policy_trees, evaluate_policy, optimal, rollout
from .gradients import SoftmaxPolicy, check_gradient, policy_value_gradient, train_policy


class ExactControlTests(unittest.TestCase):
    def test_dp_matches_independent_contingent_tree_enumeration(self):
        for risk in (0.0, 0.7):
            config = Config(budget=3, horizon=3, durations=(1, 1),
                            dynamic_preferences=False, risk=risk)
            env = Environment(config)
            dp, policy, _ = optimal(env)
            oracle, count = enumerate_policy_trees(env)
            self.assertGreater(count, 100)
            self.assertAlmostEqual(dp, oracle, places=12)
            self.assertAlmostEqual(evaluate_policy(env, policy), dp, places=12)

    def test_three_branch_dynamic_preference_dp_value(self):
        env = Environment(Config(branches=3, budget=6, horizon=7))
        dp, policy, _ = optimal(env)
        self.assertAlmostEqual(evaluate_policy(env, policy), dp, places=12)
        for seed in range(40):
            terminal, trace = rollout(env, policy, seed)
            self.assertEqual(sum(row["cost"] for row in trace), env.config.budget - terminal.budget)
            self.assertEqual(sum(row["duration"] for row in trace), terminal.elapsed)
            self.assertTrue(all(terminal.quality))
            self.assertGreaterEqual(terminal.budget, 0)
            self.assertLessEqual(terminal.elapsed, env.config.horizon)

    def test_hard_delivery_reserve_applies_before_utility(self):
        env = Environment(Config(budget=2, horizon=3))
        self.assertNotIn("stop", env.actions(env.initial))
        first = env.transitions(env.initial, "generate_0")[0][1]
        self.assertEqual(env.actions(first), ("generate_1",))
        terminal = env.transitions(first, "generate_1")[0][1]
        self.assertEqual(env.actions(terminal), ("stop",))
        with self.assertRaises(ValueError):
            env.terminal_value(first)
        with self.assertRaises(ValueError):
            env.transitions(first, "verify")
        with self.assertRaises(ValueError):
            Config(branches=3, budget=2)

    def test_actual_duration_discount_not_one_discount_per_action(self):
        env = Environment(Config(budget=2, horizon=3, risk=0, dynamic_preferences=False))
        policy = lambda s: "generate_0" if s.quality[0] == 0 else (
            "generate_1" if s.quality[1] == 0 else "stop")
        terminal_mean = 0.0
        for p0, s0 in env.transitions(env.initial, "generate_0"):
            for p1, s1 in env.transitions(s0, "generate_1"):
                terminal_mean += p0 * p1 * env.terminal_value(s1)
        expected = -env.config.cost_weight * (1 + env.config.discount)
        expected += env.config.discount ** 3 * terminal_mean
        self.assertAlmostEqual(evaluate_policy(env, policy), expected, places=13)

    def test_preference_transition_uses_elapsed_duration(self):
        env = Environment()
        one = sum(p for p, s in env.transitions(env.initial, "generate_0") if s.preference == 1)
        two = sum(p for p, s in env.transitions(env.initial, "generate_1") if s.preference == 1)
        self.assertAlmostEqual(one, 0.2)
        self.assertAlmostEqual(two, 0.32)
        fixed = Environment(replace(env.config, dynamic_preferences=False))
        self.assertTrue(all(s.preference == 0 for _, s in fixed.transitions(fixed.initial, "generate_1")))

    def test_risk_recursion_monotonicity_translation_and_zero_limit(self):
        x, p = np.array([-0.2, 1.1, 2.0]), np.array([0.2, 0.5, 0.3])
        for risk in (0.0, 1e-12, 0.4, 1000.0):
            v = certainty_equivalent(x, p, risk)
            self.assertLessEqual(v, p @ x + 1e-12)
            self.assertAlmostEqual(certainty_equivalent(x + 2, p, risk), v + 2, places=11)
            self.assertGreaterEqual(certainty_equivalent(x + np.array([0.1, 0, 0]), p, risk), v)
        self.assertAlmostEqual(certainty_equivalent(x, p, 1e-12), p @ x, places=10)
        self.assertEqual(certainty_equivalent([-1e300, 2], [0, 1], 1), 2)
        with self.assertRaises(ValueError):
            certainty_equivalent(x, [0.2, 0.5, 0.300001], 1)

    def test_gradient_matches_complete_policy_objective(self):
        for risk in (0.0, 1e-12, 0.7):
            env = Environment(Config(budget=4, horizon=5, risk=risk))
            policy = SoftmaxPolicy(env, seed=7)
            result = check_gradient(policy, max_coordinates=24)
            self.assertLess(result["max_absolute_error"], 2e-8)
            value, derivative = policy_value_gradient(policy)
            self.assertAlmostEqual(value, evaluate_policy(env, policy), places=12)
            self.assertTrue(np.allclose(derivative.sum(axis=1), 0, atol=1e-12))
            for state in policy.states:
                illegal = set(env.action_names) - set(env.actions(state))
                for action in illegal:
                    self.assertEqual(derivative[policy.rows[state], policy.actions.index(action)], 0)

    def test_plain_and_ndu_policy_learning_have_measured_gaps(self):
        for risk in (0.0, 0.25):
            env = Environment(Config(budget=4, horizon=5, risk=risk))
            policy, report = train_policy(env, seed=3, steps=70)
            self.assertGreater(report["learned_value"], report["initial_value"])
            self.assertGreaterEqual(report["optimality_gap"], -1e-12)
            self.assertLess(report["optimality_gap"], 0.008)
            self.assertAlmostEqual(evaluate_policy(env, policy), report["learned_value"], places=12)

    def test_external_task_success_cannot_be_rewritten_by_preferences(self):
        state = State((2, 2), 0, 0, 3, True)
        env = Environment()
        other = Environment(Config(interaction=0, risk=0, dynamic_preferences=False))
        self.assertEqual(env.external_metrics(state), other.external_metrics(replace(state, preference=1)))
        self.assertTrue(env.external_metrics(state)["joint_success"])
        self.assertFalse(env.external_metrics(replace(state, verified=False))["joint_success"])
        self.assertFalse(env.external_metrics(replace(state, quality=(2, 1)))["joint_success"])

    def test_invalid_state_cannot_bypass_constraints(self):
        env = Environment()
        for state in (State((2, 2), 0, -1, 0), State((2, 2), 0, 1, 99),
                      State((0, 0), 0, 6, 0, True), State((1, 2), 2, 1, 3)):
            with self.assertRaises(ValueError):
                env.actions(state)

    def test_invalid_policy_oracle_exhaustion_are_not_silent_success(self):
        env = Environment(Config(budget=3, horizon=3, durations=(1, 1), dynamic_preferences=False))
        for policy in (lambda s: {"stop": 1}, lambda s: {"generate_0": -1, "generate_1": 2}):
            with self.assertRaises(ValueError):
                evaluate_policy(env, policy)
        with self.assertRaises(ValueError):
            enumerate_policy_trees(env, limit=1)


if __name__ == "__main__":
    unittest.main()
