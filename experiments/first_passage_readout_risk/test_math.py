"""Fixed-array mathematical checks; no RNG, encoder execution or optimizer fit."""

import math
import unittest

import numpy as np

from .risk import ARMS, evaluate, objective


class ReadoutMathematics(unittest.TestCase):
    def setUp(self):
        self.features = np.array([
            [[-1.0, 0.3, 1.2], [0.7, -0.5, 0.1]],
            [[1.4, 0.1, -0.2], [-0.9, 0.4, 0.8]],
            [[0.2, -1.1, 0.3], [0.9, 0.6, -0.4]],
        ])
        self.labels = np.array([0.0, 1.0, 1.0])
        self.parameters = np.array([0.2, -0.4, 0.3, 0.1])

    def test_analytic_gradients_against_centered_objective_differences(self):
        for arm in ARMS:
            _, analytic = objective(self.parameters, self.features, self.labels, arm)
            numeric = np.empty(4)
            for coordinate in range(4):
                direction = np.zeros(4)
                direction[coordinate] = 1e-5
                plus = objective(self.parameters + direction, self.features, self.labels, arm)[0]
                minus = objective(self.parameters - direction, self.features, self.labels, arm)[0]
                numeric[coordinate] = (plus - minus) / 2e-5
            np.testing.assert_allclose(analytic, numeric, rtol=2e-8, atol=2e-10)

    def test_jensen_and_equal_objectives_when_rollouts_coincide(self):
        mean_loss = objective(self.parameters, self.features, self.labels, ARMS[0])[0]
        risk_loss = objective(self.parameters, self.features, self.labels, ARMS[1])[0]
        self.assertGreater(risk_loss, mean_loss)
        identical = np.repeat(self.features[:, :1], 3, axis=1)
        a, da = objective(self.parameters, identical, self.labels, ARMS[0])
        b, db = objective(self.parameters, identical, self.labels, ARMS[1])
        self.assertAlmostEqual(a, b, places=14)
        np.testing.assert_allclose(da, db, atol=1e-14, rtol=1e-14)

    def test_evaluation_averages_single_rollout_losses_not_features_or_probabilities(self):
        cache = {"features": np.array([[[-2.0, 0, 0], [2.0, 0, 0]]]),
                 "labels": np.array([1.0]), "native_logits": np.zeros((1, 2))}
        head = {"parameters": [1.0, 0, 0, 0], "train_mean": [0.0] * 3, "train_scale": [1.0] * 3}
        result = evaluate(cache, {arm: head for arm in ARMS})
        expected = (math.log1p(math.exp(2)) + math.log1p(math.exp(-2))) / 2
        for arm in ARMS:
            self.assertAlmostEqual(result[arm]["mean_single_rollout_bce"], expected, places=14)
            self.assertGreater(result[arm]["mean_single_rollout_bce"], math.log(2))
        self.assertAlmostEqual(result["original_native_head"]["mean_single_rollout_bce"], math.log(2), places=14)


if __name__ == "__main__":
    unittest.main()
