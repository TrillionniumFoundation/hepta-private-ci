"""Independent numeric checks of shared gradients and out-of-family scoring."""

import math
import unittest

import numpy as np

from .core import Config, Environment, State, evaluate_policy, optimal, rollout
from .experiments import ACTION_ORDER, SharedRouter, features, fixed_policy, fixed_cyclic_policy
from .experiments import limited_planner, score_policy, task_configs, train_router
from .gradients import SoftmaxPolicy, policy_value_gradient


def forward_statistics(env, choose):
    """Independent forward mass propagation, unlike score_policy's backward law."""
    states = SoftmaxPolicy(env).states
    occupancy, terminal = {env.initial: 1.0}, {}
    cost, duration, decisions = 0.0, 0.0, 0.0
    for state in states:
        mass = occupancy.get(state, 0.0)
        if mass == 0:
            continue
        decisions += mass
        choice = choose(state)
        distribution = {choice: 1.0} if isinstance(choice, str) else choice
        for action, probability in distribution.items():
            branch_mass = mass * probability
            if action == "stop":
                terminal[state] = terminal.get(state, 0.0) + branch_mass
            else:
                c, d = env.cost_duration(action)
                cost += branch_mass * c
                duration += branch_mass * d
                for outcome_probability, successor in env.transitions(state, action):
                    occupancy[successor] = occupancy.get(successor, 0.0) + branch_mass * outcome_probability
    return terminal, cost, duration, decisions


class SharedExperimentTests(unittest.TestCase):
    def test_shared_weight_gradient_matches_independent_objective_difference(self):
        configurations = [Config(budget=3, horizon=4),
                          Config(branches=3, budget=4, horizon=5, risk=0.6)]
        for freeze, no_interaction in ((False, False), (True, False), (False, True)):
            environments = [Environment(c) for c in configurations]
            rng = np.random.default_rng(174)
            weights = rng.normal(0, 0.15, (features(environments[0], environments[0].initial).size, 5))
            analytic = np.zeros_like(weights)
            for env in environments:
                policy = SoftmaxPolicy(env)
                matrix = np.stack([features(env, state, freeze, no_interaction) for state in policy.states])
                columns = [ACTION_ORDER.index(a) for a in policy.actions]
                policy.theta = matrix @ weights[:, columns]
                _, logits_gradient = policy_value_gradient(policy)
                analytic[:, columns] += matrix.T @ logits_gradient / len(environments)

            def objective(candidate):
                router = SharedRouter(candidate, freeze, no_interaction)
                return np.mean([evaluate_policy(env, router.policy(env)) for env in environments])

            flat_coordinates = rng.choice(weights.size, 14, replace=False)
            coordinates = [np.unravel_index(int(i), weights.shape) for i in flat_coordinates]
            coordinates += [(0, column) for column in range(5)]
            for index in coordinates:
                plus, minus = weights.copy(), weights.copy()
                plus[index] += 1e-5
                minus[index] -= 1e-5
                numerical = (objective(plus) - objective(minus)) / 2e-5
                self.assertAlmostEqual(analytic[index], numerical, delta=2e-8)
            self.assertTrue(np.allclose(analytic.sum(axis=1), 0.0, atol=1e-12))
            if no_interaction:
                np.testing.assert_array_equal(analytic[-4:], 0.0)

    def test_feature_ablation_preserves_joint_reward_and_verification_incentive(self):
        config = Config(budget=4, horizon=5)
        env = Environment(config)
        router, receipt = train_router([config], seed=31, variant="no_interaction", steps=3)
        # Re-evaluate on the original environment, independently of the trainer's
        # reported objective. Removing its joint reward would fail this equality.
        self.assertAlmostEqual(receipt["final_training_value"],
                               evaluate_policy(env, router.policy(env)), places=12)
        self.assertTrue(receipt["joint_reward_preserved"])
        state = State((2, 2), 0, 1, 3)
        ordinary = features(env, state)
        ablated = features(env, state, no_interaction_features=True)
        np.testing.assert_array_equal(ablated[:-4], ordinary[:-4])
        np.testing.assert_array_equal(ablated[-4:], 0.0)
        self.assertGreater(np.linalg.norm(ordinary[-4:]), 0.0)
        stop_value = env.terminal_value(state)
        value, decisions, _ = optimal(env, start=state)
        self.assertGreater(value, stop_value)
        self.assertEqual(decisions[state], "verify")

    def test_fixed_cyclic_allocation_spends_spare_quota_and_reserves_verification(self):
        configurations = [
            Config(budget=6, horizon=6, durations=(1, 1), success_probabilities=(0.0, 0.0)),
            Config(branches=3, budget=7, horizon=7, durations=(1, 1, 1),
                   success_probabilities=(0.0, 0.0, 0.0)),
            Config(budget=7, horizon=8, costs=(2, 1), success_probabilities=(0.0, 0.0)),
        ]
        for config in configurations:
            env = Environment(config)
            cyclic = lambda state: fixed_cyclic_policy(env, state)
            report = score_policy(env, cyclic)
            single = score_policy(env, lambda state: fixed_policy(env, state))
            self.assertGreater(report["expected_generation_compute_units"],
                               single["expected_generation_compute_units"])
            self.assertAlmostEqual(report["expected_generation_compute_units"], config.budget, places=12)
            self.assertEqual(report["missing_delivery_rate"], 0.0)
            self.assertEqual(report["unchecked_cross_modal_rate"], 0.0)
            self.assertEqual(report["budget_violations"], 0.0)
            final, trace = rollout(env, cyclic, seed=17)
            self.assertTrue(final.verified)
            self.assertEqual(trace[-1]["action"], "verify")
            self.assertEqual(sum(step["cost"] for step in trace), config.budget)
            self.assertLessEqual(sum(step["duration"] for step in trace), config.horizon)

    def test_heldout_transfer_preserves_parameters_probabilities_and_accounting(self):
        tasks = task_configs()
        router, receipt = train_router([tasks["train_text_image"], tasks["train_three_branch"]],
                                       seed=19, steps=3)
        frozen = router.weights.copy()
        self.assertEqual(receipt["trainable_parameters"], router.weights.size)
        for name, config in tasks.items():
            if not name.startswith("heldout_"):
                continue
            env, choose = Environment(config), None
            choose = router.policy(env)
            terminal, cost, duration, decisions = forward_statistics(env, choose)
            report = score_policy(env, choose)
            self.assertAlmostEqual(math.fsum(terminal.values()), 1.0, places=12)
            self.assertAlmostEqual(cost, report["expected_generation_compute_units"], places=12)
            self.assertAlmostEqual(duration, report["expected_generation_duration_ticks"], places=12)
            self.assertAlmostEqual(decisions, report["expected_decision_count"], places=12)
            self.assertAlmostEqual(report["joint_success_rate"], math.fsum(
                p * env.external_metrics(state)["joint_success"] for state, p in terminal.items()), places=12)
            self.assertEqual(report["budget_violations"], 0.0)
            self.assertEqual(report["missing_delivery_rate"], 0.0)
            self.assertLessEqual(cost, config.budget)
            self.assertLessEqual(duration, config.horizon)
            for state in terminal:
                self.assertTrue(all(state.quality))
                self.assertGreaterEqual(state.budget, 0)
                self.assertLessEqual(state.elapsed, config.horizon)
            np.testing.assert_array_equal(router.weights, frozen)

    def test_lower_tail_uses_fractional_probability_at_quantile(self):
        env = Environment(Config(budget=3, horizon=4, success_probabilities=(0.99, 0.99)))
        report = score_policy(env, lambda state: fixed_policy(env, state))
        low_quality_mass = 1 - 0.99 ** 2
        expected = (low_quality_mass * 0.5 + (0.1 - low_quality_mass)) / 0.1
        self.assertAlmostEqual(report["weakest_quality_lower_tail_mean_10pct"], expected, places=12)
        self.assertAlmostEqual(report["joint_success_rate"], 0.99 ** 2, places=12)
        self.assertAlmostEqual(report["expected_decision_count"], 4.0, places=12)
        self.assertAlmostEqual(report["expected_generation_compute_units"], 3.0, places=12)
        self.assertAlmostEqual(report["expected_generation_duration_ticks"], 4.0, places=12)

    def test_oracle_continuation_planner_is_legal_and_value_bounded(self):
        env = Environment(Config(budget=3, horizon=4))
        weights = np.zeros((features(env, env.initial).size, 5))
        continuation = SharedRouter(weights).policy(env)
        planner, counts = limited_planner(env, continuation, depth=2)
        report = score_policy(env, planner)
        self.assertGreaterEqual(report["recursive_value"] + 1e-12, evaluate_policy(env, continuation))
        self.assertLessEqual(report["recursive_value"], optimal(env)[0] + 1e-12)
        self.assertEqual(report["budget_violations"], 0.0)
        self.assertEqual(report["missing_delivery_rate"], 0.0)
        self.assertGreater(counts["expanded_states"], 0)
        self.assertGreater(counts["leaf_policy_evaluations"], 0)


if __name__ == "__main__":
    unittest.main()
