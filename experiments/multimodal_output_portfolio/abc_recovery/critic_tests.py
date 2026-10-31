"""Analytic backups and real Torch optimization; no neural calibration claim."""

import math
import unittest

import torch

from .critic import ActionCritic, FiniteHorizonCritic, bootstrap_two_step_targets, fit_one_step, fit_two_step, terminal_targets


def constant_head(values, gamma=2.0, remaining=1):
    model = ActionCritic(3, gamma, remaining, seed=17, hidden_dim=8)
    with torch.no_grad():
        for parameter in model.parameters():
            parameter.zero_()
        values = torch.tensor(values, dtype=torch.float32)
        raw = values if gamma == 0 else torch.log(torch.expm1(values))
        model.network[-1].bias.copy_(raw)
    return model


class CriticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous_threads = torch.get_num_threads()
        torch.set_num_threads(1)

    @classmethod
    def tearDownClass(cls):
        torch.set_num_threads(cls.previous_threads)

    def test_terminal_targets_match_actual_utility_and_zero_stop_cost(self):
        utility = torch.tensor([[0.5, 0.2, -0.2, 1.0, 0.0], [-0.1, 0.0, 0.7, 0.4, 0.2]])
        costs = (0.01, 0.02, 0.03, 0.04)
        for gamma in (0.0, 2.0):
            reference = [[c - u if gamma == 0 else math.exp(gamma * (c - u)) for c, u in zip((0.0,) + costs, row)] for row in utility.tolist()]
            torch.testing.assert_close(terminal_targets(utility, gamma, costs), torch.tensor(reference))

    def test_two_step_backup_uses_frozen_predictions_and_feasible_actions(self):
        model = constant_head((0.8, 0.6, 0.5, 0.4, 0.7))
        children = torch.zeros(2, 4, 3)
        masks = torch.ones(2, 4, 5, dtype=torch.bool)
        masks[:, 0] = torch.tensor([True, False, False, False, False])
        stop = torch.tensor([0.3, -0.1])
        costs = torch.tensor([[0.01, 0.02, 0.03, 0.04], [0.04, 0.03, 0.02, 0.01]])
        actual = bootstrap_two_step_targets(stop, children, model, costs, masks)
        reference = [[math.exp(-2 * u)] + [math.exp(2 * c) * z for c, z in zip(row, (0.8, 0.4, 0.4, 0.4))] for u, row in zip(stop.tolist(), costs.tolist())]
        torch.testing.assert_close(actual, torch.tensor(reference))
        changed_stop = bootstrap_two_step_targets(stop + 0.1, children, model, costs, masks)
        torch.testing.assert_close(actual[:, 1:], changed_stop[:, 1:])
        self.assertFalse(torch.equal(actual[:, 0], changed_stop[:, 0]))
        with self.assertRaises(TypeError):
            fit_two_step(torch.zeros(2, 3), stop, children, model, 1, 1, realized_grandchild_utility=torch.ones(2, 4, 5))

    def test_neutral_backup_is_cost_minus_utility(self):
        model = constant_head((-0.2, 0.1, 0.3, 0.4, 0.5), gamma=0.0)
        actual = bootstrap_two_step_targets(torch.tensor([0.3]), torch.zeros(1, 4, 3), model, 0.05)
        torch.testing.assert_close(actual, torch.tensor([[-0.3, -0.15, -0.15, -0.15, -0.15]]))

    def test_actual_optimization_reduces_moment_and_neutral_fit_loss(self):
        features = torch.linspace(-1, 1, 96).reshape(32, 3)
        targets = torch.stack([0.5 + 0.2 * torch.sin(features[:, 0] + a * 0.3) + 0.05 * features[:, 1] for a in range(5)], dim=1)
        for gamma in (0.0, 2.0):
            fitted = fit_one_step(features, targets, seed=29, steps=150, gamma=gamma, hidden_dim=16, batch_size=32, learning_rate=0.01)
            self.assertLess(fitted.fit_report["final_full_mse"], 0.1 * fitted.fit_report["initial_full_mse"])
            values = fitted.predict(features)
            self.assertTrue(torch.isfinite(values).all())
            if gamma > 0:
                self.assertTrue((values > 0).all())

    def test_local_seed_repeats_and_preserves_callers_rng(self):
        features = torch.linspace(-1, 1, 60).reshape(20, 3)
        targets = torch.ones(20, 5) * 0.4
        before = torch.random.get_rng_state().clone()
        a = fit_one_step(features, targets, 43, 20, batch_size=7)
        b = fit_one_step(features, targets, 43, 20, batch_size=7)
        self.assertEqual(a.fit_report, b.fit_report)
        for name, value in a.state_dict().items():
            self.assertTrue(torch.equal(value, b.state_dict()[name]), name)
        self.assertTrue(torch.equal(before, torch.random.get_rng_state()))

    def test_fit_two_step_does_not_train_or_change_one_step_head(self):
        one = constant_head((0.8, 0.6, 0.5, 0.4, 0.7))
        before = {name: value.clone() for name, value in one.state_dict().items()}
        original_mode = one.training
        roots = torch.linspace(-1, 1, 60).reshape(20, 3)
        children = roots[:, None, :].expand(20, 4, 3)
        two = fit_two_step(roots, 0.3 + 0.1 * roots[:, 0], children, one, 17, 100, learning_rate=0.01)
        self.assertLess(two.fit_report["final_full_mse"], 0.1 * two.fit_report["initial_full_mse"])
        self.assertEqual((two.remaining, two.gamma), (2, one.gamma))
        self.assertFalse(two.fit_report["realized_grandchild_labels_used"])
        self.assertEqual(one.training, original_mode)
        for name, value in one.state_dict().items():
            self.assertTrue(torch.equal(value, before[name]), name)
        self.assertTrue(all(parameter.grad is None for parameter in one.parameters()))

    def test_greedy_inference_uses_remaining_and_boolean_feasibility(self):
        one = constant_head((0.5, 0.2, 0.3, 0.4, 0.6))
        two = constant_head((0.1, 0.2, 0.3, 0.4, 0.5), remaining=2)
        critic = FiniteHorizonCritic(one, two)
        features = torch.zeros(2, 3)
        mask = torch.tensor([[True, False, True, True, True], [False, False, False, False, True]])
        self.assertEqual(critic.select_actions(features, torch.tensor([1, 2]), mask).tolist(), [2, 4])
        self.assertEqual(critic.select_actions(features, 2, torch.ones(2, 5, dtype=torch.bool)).tolist(), [0, 0])
        with self.assertRaises(ValueError):
            critic.select_actions(features, 1, torch.zeros(2, 5, dtype=torch.bool))
        with self.assertRaises(ValueError):
            critic.select_actions(features, 1, torch.ones(2, 5))
        with self.assertRaises(ValueError):
            critic.select_actions(features, 1.5, mask)

    def test_invalid_profiles_shapes_and_values_are_rejected(self):
        features = torch.zeros(2, 3)
        one = constant_head((0.8, 0.6, 0.5, 0.4, 0.7))
        for targets in (torch.zeros(2, 5), torch.full((2, 5), float("nan")), torch.ones(2, 4)):
            with self.assertRaises(ValueError):
                fit_one_step(features, targets, 1, 1)
        with self.assertRaises(ValueError):
            fit_one_step(features + float("nan"), torch.ones(2, 5), 1, 1)
        with self.assertRaises(ValueError):
            terminal_targets(torch.full((2, 5), -1000.0), 2)
        with self.assertRaises(ValueError):
            fit_two_step(features, torch.zeros(2), torch.zeros(2, 4, 3), one, 1, 1, gamma=0)
        with self.assertRaises(ValueError):
            bootstrap_two_step_targets(torch.zeros(2), torch.zeros(2, 4, 2), one)
        with self.assertRaises(ValueError):
            bootstrap_two_step_targets(torch.zeros(2), torch.zeros(2, 4, 3), one, action_costs=-0.1)

    def test_cpu_float32_contract_ignores_callers_default_float_dtype(self):
        previous = torch.get_default_dtype()
        try:
            torch.set_default_dtype(torch.float64)
            model = ActionCritic(3, 2, 1, 17)
            values = model.predict(torch.zeros(2, 3))
            self.assertEqual((values.dtype, values.device.type), (torch.float32, "cpu"))
            targets = terminal_targets(torch.zeros(2, 5), 2)
            self.assertEqual((targets.dtype, targets.device.type), (torch.float32, "cpu"))
        finally:
            torch.set_default_dtype(previous)


if __name__ == "__main__":
    unittest.main()
