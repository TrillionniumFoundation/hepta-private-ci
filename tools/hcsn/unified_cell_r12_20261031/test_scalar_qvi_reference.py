"""Scalar closed-form contract tests independent of the finite task model."""
import unittest

import numpy as np

from .scalar_qvi_reference import ScalarParameters, ScalarQVI, run_scalar_reference


class ScalarReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = run_scalar_reference()

    def test_reproduces_old_committed_benchmark(self):
        for row in self.report["cases"]:
            self.assertLess(row["old_boundary_absolute_error"], 3e-14)
            self.assertLess(row["old_gradient_max_absolute_error"], 3e-13)
            self.assertLess(abs(row["root_residual"]), 3e-15)

    def test_value_matching_smooth_fit_and_global_inequalities(self):
        for row in self.report["cases"]:
            self.assertLess(row["value_matching_error"], 3e-14)
            self.assertAlmostEqual(row["left_slope"], 1., delta=6e-7)
            self.assertAlmostEqual(row["right_slope"], 1., delta=2e-9)
            self.assertGreaterEqual(row["minimum_obstacle_gap"], -3e-14)
            self.assertLess(row["maximum_generator_residual"], 3e-14)
            self.assertLess(row["maximum_qvi_residual"], 3e-14)

    def test_six_implicit_derivatives_and_separate_optimizer(self):
        for row in self.report["cases"]:
            self.assertLess(max(v["scaled_error"] for v in row["derivative_checks"].values()), 8e-9)
            self.assertTrue(row["separate_optimizer_success"])
            self.assertLess(row["separate_threshold_optimizer_error"], 2e-6)

    def test_renewal_value_and_obstacle_semantics(self):
        solution = ScalarQVI()
        points = np.array([-5., -.2, .8, solution.boundary, solution.boundary+2])
        np.testing.assert_allclose(solution.value(points),
                                   solution.fixed_threshold_value(points, solution.boundary), rtol=0, atol=1e-14)
        np.testing.assert_allclose(solution.obstacle_gap(points[-2:]), 0., rtol=0, atol=1e-14)
        gradients = solution.boundary_gradients()
        self.assertAlmostEqual(gradients["K"]+gradients["r"], 1., places=13)

    def test_conditioning_is_reported_and_invalid_regimes_not_clipped(self):
        near = self.report["near_degenerate"]
        self.assertGreater(near["gradients"]["K"], 100.)
        self.assertLess(near["root_jacobian"], .01)
        for p in (ScalarParameters(r=.8), ScalarParameters(rho=0.), ScalarParameters(sigma=0.),
                  ScalarParameters(tau=-1.)):
            with self.assertRaises(ValueError):
                ScalarQVI(p)


if __name__ == "__main__":
    unittest.main()
