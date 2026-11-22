"""Independent optimality checks for the conditional optimization comparison."""

import unittest

import torch

from .readout import objective, optimality, solve_bp
from .representation import ridge_fit


class ReadoutTests(unittest.TestCase):
    def test_bp_and_svd_reach_independent_linear_system(self):
        x = torch.tensor(
            [[-2.0, 0.0], [-1.0, 2.0], [0.0, -1.0], [1.0, 1.0], [2.0, 3.0]],
            dtype=torch.float64,
        )
        y = torch.tensor([-0.8, 0.3, 0.9, 0.5, 1.2], dtype=x.dtype)
        ridge = 0.03
        design = torch.cat((x, torch.ones_like(x[:, :1])), 1)
        penalty = torch.diag(torch.tensor([ridge, ridge, 0.0], dtype=x.dtype))
        expected = torch.linalg.solve(design.T @ design + penalty, design.T @ y)
        direct = ridge_fit(x, y, ridge=ridge)
        cfg = {
            "max_iterations": 512,
            "max_evaluations": 1024,
            "gradient_tolerance": 1e-11,
            "change_tolerance": 1e-15,
            "checkpoints": [16, 64],
        }
        bp, cost = solve_bp(
            x, y, ridge, {"weight": x.new_zeros(2), "bias": x.new_zeros(())}, cfg
        )
        for result in (direct, bp):
            actual = torch.cat(
                (result["weight"], torch.as_tensor(result["bias"]).reshape(1))
            )
            torch.testing.assert_close(actual, expected, atol=2e-7, rtol=2e-7)
        self.assertGreater(cost["backward_evaluations"], 0)
        check = optimality(x, y, bp, ridge, direct)
        self.assertLess(abs(check["objective_gap"]), 1e-12)

    def test_gradient_bound_covers_real_excess(self):
        x = torch.tensor(
            [[-1.0, 2.0], [0.0, 1.0], [2.0, 0.0], [3.0, 4.0]], dtype=torch.float64
        )
        y = torch.tensor([0.2, 0.8, 0.5, 0.1], dtype=x.dtype)
        optimum = ridge_fit(x, y, ridge=0.1)
        trial = {
            "weight": torch.tensor([0.5, -0.2], dtype=x.dtype),
            "bias": x.new_tensor(0.3),
        }
        check = optimality(x, y, trial, 0.1, optimum)
        self.assertGreater(check["objective_gap"], 0)
        self.assertGreaterEqual(
            check["gradient_objective_bound"], check["objective_gap"] - 1e-12
        )

    def test_regularizer_never_penalizes_intercept(self):
        x = torch.zeros(6, 2, dtype=torch.float64)
        y = torch.full((6, 1), 7.0, dtype=x.dtype)
        fitted = ridge_fit(x, y, ridge=10.0)
        self.assertAlmostEqual(
            float(objective(x, y, fitted["weight"], fitted["bias"], 10.0)), 0.0
        )
        self.assertAlmostEqual(float(fitted["bias"]), 7.0)


if __name__ == "__main__":
    unittest.main()
