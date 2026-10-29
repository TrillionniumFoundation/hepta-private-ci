"""Structural and native integration checks for learned Bellman operators."""

import unittest

import numpy as np
import torch

from experiments.first_passage_operator.bellman import BellmanLayer
from experiments.first_passage_operator.markov import BIN_COUNT
from experiments.first_passage_operator.operators import RegenerativeSpec
from experiments.first_passage_operator.value_learning import RegenerativeValueLayer, contexts


class ValueLayerTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        torch.manual_seed(81)
        self.model = RegenerativeValueLayer()

    def test_positive_mass_and_discounted_partition(self):
        rows = torch.from_numpy(contexts(64, 83))
        moments, transition = self.model.outputs(rows)
        np.testing.assert_allclose(transition.detach().sum(dim=1), 1, atol=3e-15)
        np.testing.assert_allclose((moments[:, 0] + moments[:, 5]).detach(),
                                   torch.exp(-rows[:, 4] * rows[:, 6]), atol=3e-15)
        self.assertGreaterEqual(float(moments.detach().min()), 0)
        self.assertGreaterEqual(float(transition.detach().min()), 0)

    def test_exact_holding_and_release(self):
        rows = torch.tensor([[-0.4, .3, .9, .12, .2, .9, .04, .08],
                             [-0.4, .3, .9, .12, .2, .9, .08, .08]], dtype=torch.float64)
        moments, transition = self.model.outputs(rows)
        np.testing.assert_array_equal(moments[0, :5].detach(), 0)
        np.testing.assert_allclose(moments[0, 5:8].detach(),
                                   np.exp(-.2*.04) * np.exp(-np.array([0, 1, 3])*.04/.12), atol=1e-15)
        np.testing.assert_allclose(moments[1, :5].detach(),
                                   np.exp(-.2*.08) * np.exp(-np.array([0, .5, 1, 2, 4])*.9), atol=1e-15)
        np.testing.assert_array_equal(moments[:, 8:].detach(), 0)
        np.testing.assert_array_equal((transition > 0).sum(dim=1).detach(), 1)

    def test_initial_boundary_atom_precedes_zero_horizon(self):
        row = torch.tensor([[-.55, .32, .9, .06, .2, 0., 0., 0.]], dtype=torch.float64)
        moments, probability = self.model.outputs(row)
        np.testing.assert_array_equal(moments[0, :5].detach(), 0)
        np.testing.assert_allclose(moments[0, 5:8].detach(), np.exp(-np.array([0., 1., 3.])), atol=1e-15)
        self.assertEqual(float(moments[0, 8].detach()), 1.)
        self.assertEqual(float(moments[0, 9].detach()), 0.)
        self.assertEqual(float(probability[0, -1].detach()), 1.)

    def test_payoff_linearity_and_exact_branch_gradient(self):
        rows = torch.from_numpy(contexts(10, 91))
        one = torch.randn(10, 10, dtype=torch.float64, requires_grad=True)
        two = torch.randn(10, 10, dtype=torch.float64)
        np.testing.assert_allclose(self.model(rows, 2*one-3*two).detach(),
                                   (2*self.model(rows, one)-3*self.model(rows, two)).detach(), atol=1e-14)
        derivative = torch.autograd.grad(self.model(rows, one).sum(), one)[0]
        np.testing.assert_allclose(derivative, self.model.moments(rows).detach(), atol=0)

    def test_transition_backup_monotonicity_and_nonexpansiveness(self):
        rows = torch.from_numpy(contexts(20, 97))
        probability = self.model.transition_probabilities(rows).detach().numpy()
        rng = np.random.default_rng(101)
        left = rng.normal(size=BIN_COUNT)
        right = left + rng.random(BIN_COUNT)
        self.assertTrue(np.all(probability @ right >= probability @ left - 1e-14))
        self.assertLessEqual(float(np.max(np.abs(probability @ (right-left)))),
                             float(np.max(np.abs(right-left))) + 1e-14)

    def test_invalid_refractory_state_rejected(self):
        rows = torch.from_numpy(contexts(4, 103))
        rows[0, 7] = rows[0, 3] / 2
        rows[0, 5] = rows[0, 2] + 1
        with self.assertRaises(ValueError):
            self.model.outputs(rows)

    def test_finite_horizon_values_and_last_step(self):
        planner = BellmanLayer(RegenerativeSpec(-.55, .32, .9, .06), self.model)
        layers = planner.fit(.2)
        self.assertEqual(len(layers), 5)
        np.testing.assert_array_equal(layers[0], np.zeros(BIN_COUNT))
        for index, value in enumerate(layers):
            self.assertGreaterEqual(float(value.min()), 0)
            self.assertLessEqual(float(value.max()), .3*index + 1e-12)
        observation = {"level": .4, "refractory_remaining": 0., "decision_index": 3,
                       "repair_cost": .2, "legal_actions": ["wait", "repair", "stop"]}
        paths, predictions = planner.forecast(observation, layers)
        self.assertEqual(set(paths), {"WAIT", "REPAIR", "STOP"})
        self.assertEqual({name: row["terminal"] for name, row in paths.items()},
                         {"WAIT": 0., "REPAIR": 0., "STOP": 0.})
        self.assertEqual(predictions["WAIT"]["continuation"], 0.)


if __name__ == "__main__":
    unittest.main()
