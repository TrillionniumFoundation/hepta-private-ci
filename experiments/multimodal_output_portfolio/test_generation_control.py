"""Contract, independent finite-policy, and selected-policy gradient checks."""

from dataclasses import FrozenInstanceError
import gc
from itertools import product
import math
import unittest
import weakref

import numpy as np

from control import CalibrationModel, portfolio_grid
from generation_control import (GenerationPlanner, InfeasibleGeneration,
                                bottom_up_reference, certainty_equivalent, generation_cost)


def sparse_model(truth, reports):
    return CalibrationModel(np.asarray(truth), np.asarray(reports), smoothing=0.0)


class GenerationControlTests(unittest.TestCase):
    def setUp(self):
        self.grid = portfolio_grid()
        self.pure = [int(np.flatnonzero(np.all(self.grid == row, axis=1))[0]) for row in np.eye(8)]
        self.model = sparse_model([0, 1], [[8, 0, 8, 8], [8, 1, 8, 8]])
        self.loss = np.full((4, len(self.grid), 8), 2.0)
        self.loss[:, self.pure[0], 0] = [0.0, 0.1, 0.2, 0.3]
        self.loss[:, self.pure[1], 1] = [0.9, 0.5, 0.1, 0.2]

    def test_ce_support_neutral_limit_and_validation(self):
        self.assertEqual(float(certainty_equivalent([-1e6, 1], [0, 1], 2)), 1)
        self.assertEqual(float(certainty_equivalent([0, 10], [.5, .5], 0)), 5)
        self.assertAlmostEqual(float(certainty_equivalent([0, 10], [.5, .5], 1)),
                               math.log(2) - math.log1p(math.exp(-10)), places=13)
        self.assertAlmostEqual(float(certainty_equivalent([0, 10], [.5, .5], 1e-12)), 5, places=9)
        for values, probabilities, gamma in [([1, 2], [1, 1], 1), ([1, 2], [-1, 2], 1),
                                             ([1, float("nan")], [.5, .5], 1), ([1], [1], -1),
                                             ([1], [1], float("nan")), ([1], [1], True)]:
            with self.subTest(values=values, probabilities=probabilities, gamma=gamma):
                with self.assertRaises(ValueError):
                    certainty_equivalent(values, probabilities, gamma)

    def test_cost_depth_and_no_false_fallback(self):
        model = sparse_model([0], [[0, 0, 0, 0]])
        losses = np.broadcast_to(np.array([.8, .4, .1, .1])[:, None, None], self.loss.shape)
        planner = GenerationPlanner(model, losses, self.grid, penalty=.1)
        for budget, depth, value in [(4, 0, -1.2), (6, 1, -1.0), (8, 2, -.9), (10, 2, -.9)]:
            plan = planner.solve((0, 0, 0, 0), budget)
            self.assertEqual((plan.action, plan.portfolio, plan.depth), (-1, self.pure[0], depth))
            self.assertAlmostEqual(plan.value, value)
            self.assertLessEqual(generation_cost(plan.depth), budget)
        for budget in range(4):
            with self.assertRaises(InfeasibleGeneration):
                planner.solve((0, 0, 0, 0), budget)
        with self.assertRaises(FrozenInstanceError):
            plan.depth = 0
        with self.assertRaises(ValueError):
            planner.solve((True, 0, 0, 0), 4)
        with self.assertRaises(ValueError):
            planner.solve((1, 0, 0, 0), 4)
        with self.assertRaises(ValueError):
            GenerationPlanner(model, losses[:, :, :7], self.grid)

    def test_supported_outputs_and_explicit_uniform_fallback(self):
        planner = GenerationPlanner(self.model, self.loss, self.grid)
        self.assertEqual(planner.candidates((8, -1, 8, 8)), (len(self.grid) - 1,))
        self.assertEqual(planner.candidates((8, 0, 8, 8)), (self.pure[0],))
        # Enough action budget without controller overhead; not enough with it.
        free = GenerationPlanner(self.model, self.loss, self.grid, controller_cost=0)
        self.assertEqual(free.solve((8, -1, 8, 8), 5).action, 1)
        self.assertEqual(planner.solve((8, -1, 8, 8), 5).action, -1)

    def test_independent_bottom_up_all_modes_and_preference_order(self):
        model = sparse_model([0, 1], [[0, 1, 0, 8], [0, 1, 0, 8]])
        losses = np.full(self.loss.shape, 3.0)
        losses[:, self.pure[0], :2] = [.1, .9]
        roots = [((0, -1, -1, -1), budget, 0) for budget in (8, 12, 16)]
        for mode in ("ndu", "fixed", "neutral", "myopic", "single"):
            planner = GenerationPlanner(model, losses, self.grid, gamma=.7, mode=mode)
            reference = bottom_up_reference(model.joint, losses, self.grid, roots, gamma=.7, mode=mode)
            for state, expected in reference.items():
                actual = planner.solve(*state)
                self.assertEqual((actual.action, actual.portfolio, actual.depth),
                                 (expected.action, expected.portfolio, expected.depth))
                self.assertAlmostEqual(actual.value, expected.value, places=11)
            if mode == "ndu":
                first, second = ((0, 1, 0, -1), 7, 1), ((0, 1, 0, -1), 7, 2)
                self.assertIn(first, reference)
                self.assertIn(second, reference)
                self.assertGreater(reference[first].value, reference[second].value)

    def test_independent_near_tie_portfolio_parity(self):
        model = sparse_model([0], [[0, 1, 8, 8]])
        losses = np.ones(self.loss.shape)
        losses[:, self.pure[0], :] = .5
        losses[:, self.pure[1], :] = .5 - 5e-13
        state = ((0, 1, 8, 8), 4, 0)
        planner = GenerationPlanner(model, losses, self.grid)
        reference = bottom_up_reference(model.joint, losses, self.grid, [state])
        self.assertEqual(planner.solve(*state), reference[state])
        self.assertEqual(planner.solve(*state).portfolio, self.pure[1])

    def test_complete_contingent_policy_enumeration(self):
        state = ((8, -1, 8, 8), 11, 0)
        planner = GenerationPlanner(self.model, self.loss, self.grid, gamma=.8)
        # Only audio is unobserved. Enumerate every contingent depth pair,
        # including different depths after the two reports, and every root stop.
        values = [-2 - .025 * (4 + 2 * d) for d in range(4)]
        for depths in product(range(3), repeat=2):
            child = [-self.loss[depths[h], self.pure[h], h] - .025 * (4 + 2 * depths[h])
                     for h in (0, 1)]
            values.append(-math.log(sum(.5 * math.exp(-.8 * v) for v in child)) / .8 - .075)
        self.assertAlmostEqual(planner.solve(*state).value, max(values), places=12)
        self.assertEqual(planner.solve(*state).action, 1)
        self.assertEqual(planner.solve((8, 0, 8, 8), 8).depth, 0)
        self.assertEqual(planner.solve((8, 1, 8, 8), 8).depth, 2)

    def test_torch_value_and_envelope_finite_difference(self):
        import torch

        state = ((8, -1, 8, 8), 11, 0)
        losses = self.loss + .05  # symmetric finite differences stay nonnegative
        planner = GenerationPlanner(self.model, losses, self.grid, gamma=.8)
        tensor = torch.tensor(losses, dtype=torch.float64, requires_grad=True)
        utility = planner.evaluate_policy_torch(tensor, *state)
        self.assertAlmostEqual(utility.item(), planner.solve(*state).value, places=12)
        utility.backward()
        for index in [(0, self.pure[0], 0), (2, self.pure[1], 1), (3, self.pure[0], 0)]:
            plus, minus = losses.copy(), losses.copy()
            plus[index] += 1e-6
            minus[index] -= 1e-6
            up = GenerationPlanner(self.model, plus, self.grid, gamma=.8).solve(*state)
            down = GenerationPlanner(self.model, minus, self.grid, gamma=.8).solve(*state)
            self.assertEqual((up.action, down.action), (1, 1))
            self.assertAlmostEqual(tensor.grad[index].item(), (up.value - down.value) / 2e-6, places=7)

    def test_caches_and_loss_snapshots_are_instance_local(self):
        planner = GenerationPlanner(self.model, self.loss, self.grid)
        self.loss[:] = 99
        self.assertNotEqual(float(planner.loss[0, 0, 0]), 99)
        planner.compile((8, 12, 16))
        before = planner.state_count
        planner.compile((8, 12, 16))
        planner.solve((8, -1, -1, -1), 8)
        planner.solve((8, -1, -1, -1), budget=8, preference=0)
        self.assertEqual(planner.state_count, before)
        other = GenerationPlanner(self.model, self.loss, self.grid)
        self.assertEqual(other.state_count, 0)
        self.assertGreater(planner.state_count, 0)
        reference = weakref.ref(planner)
        del planner
        gc.collect()
        self.assertIsNone(reference())

    def test_torch_extreme_finite_risk_uses_stable_anchor(self):
        import torch

        losses = np.full(self.loss.shape, .5)
        losses[:, :, 1] = 2.0
        planner = GenerationPlanner(self.model, losses, self.grid, gamma=1e308, mode="fixed")
        state = ((8, -1, 8, 8), 4, 0)
        utility = planner.evaluate_policy_torch(torch.tensor(losses, dtype=torch.float64), *state)
        self.assertTrue(torch.isfinite(utility))
        self.assertEqual(utility.item(), planner.solve(*state).value)


if __name__ == "__main__":
    unittest.main()
