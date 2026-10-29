"""QVI verification, derivative and independent policy iteration checks."""

from dataclasses import replace
import unittest

import numpy as np

from experiments.first_passage_operator.free_boundary import (
    NaturalSpikeSpec, optimal_value, solve_boundary, solve_grid_qvi, threshold_value,
)


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.spec = NaturalSpikeSpec(0.2, 0.5, 0.0, 0.15, 0.4, 0.4)

    def test_qvi_and_recurrent_boundary(self):
        spec = self.spec
        row = solve_boundary(spec)
        b, lam = row["boundary"], row["lambda"]
        x = np.linspace(-8, b, 600)
        value = optimal_value(spec, x)
        obstacle = x-spec.spike_cost+row["beta"]*row["reset_value"]
        self.assertGreaterEqual(float(np.min(value-obstacle)), -1e-12)
        self.assertLess(abs(row["smooth_fit_residual"]), 1e-12)
        self.assertLess(abs(row["value_matching_residual"]), 1e-12)
        self.assertAlmostEqual(spec.mu-spec.discount/lam, row["stopping_generator_at_boundary"])
        self.assertLess(row["stopping_generator_at_boundary"], 0)
        self.assertAlmostEqual(float(optimal_value(spec, spec.reset)), row["reset_value"])
        self.assertAlmostEqual(threshold_value(spec, b), row["reset_value"])
        for threshold in np.linspace(spec.spike_cost, b+2, 100):
            self.assertLessEqual(threshold_value(spec, threshold), row["reset_value"]+1e-12)

    def test_all_implicit_parameter_gradients(self):
        row = solve_boundary(self.spec)
        for name, expected in row["boundary_gradients"].items():
            delta = 1e-6
            low = replace(self.spec, **{name: getattr(self.spec, name)-delta})
            high = replace(self.spec, **{name: getattr(self.spec, name)+delta})
            actual = (solve_boundary(high)["boundary"]-solve_boundary(low)["boundary"])/(2*delta)
            self.assertAlmostEqual(actual, expected, places=7, msg=name)

    def test_independent_finite_difference_policy_iteration(self):
        exact = solve_boundary(self.spec)
        coarse = solve_grid_qvi(self.spec, spacing=0.04)
        fine = solve_grid_qvi(self.spec, spacing=0.02)
        self.assertLess(abs(fine["boundary"]-exact["boundary"]), 0.03)
        self.assertLess(abs(fine["reset_value"]-exact["reset_value"]),
                        abs(coarse["reset_value"]-exact["reset_value"]))
        self.assertLess(fine["bellman_residual"], 1e-10)

    def test_refractory_is_discounted_actual_time(self):
        row = solve_boundary(self.spec)
        self.assertAlmostEqual(float(optimal_value(self.spec, 0, pending_refractory=0.1)),
                               np.exp(-0.04)*row["reset_value"])
        with self.assertRaises(ValueError):
            optimal_value(self.spec, 1.0, pending_refractory=0.1)
        with self.assertRaises(ValueError):
            NaturalSpikeSpec(0.2, 0.5, 1.0, 0.1, 0.4, 0.5)


if __name__ == "__main__":
    unittest.main()
