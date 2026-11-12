import unittest
from dataclasses import replace

import mpmath as mp
import numpy as np

from qualification.hcsn_qvi.continuum import fixed_threshold, solve_boundary
from qualification.hcsn_qvi.oracle import FiniteControl, Problem
from qualification.hcsn_qvi.run_continuum import high_precision


class ContinuumTests(unittest.TestCase):
    def test_independent_80_digit_system_and_qvi_conditions(self):
        problem = Problem()
        result = solve_boundary(problem)
        with mp.workdps(80):
            boundary, value = high_precision(problem)
            self.assertLess(abs(mp.mpf(result.boundary) - boundary), mp.mpf("2e-10"))
            self.assertLess(abs(mp.mpf(float(result.value(problem.initial))) - value), mp.mpf("2e-10"))
        residual = result.residuals()
        for name in ("value_matching", "smooth_pasting", "upper_reflection",
                     "maximum_continuation_ode_residual"):
            self.assertLess(abs(residual[name]), 1e-10, name)
        self.assertLessEqual(residual["maximum_intervention_generator_residual"], 1e-10)
        self.assertGreaterEqual(residual["minimum_sampled_continuation_slope"], -1e-10)
        self.assertGreaterEqual(residual["minimum_sampled_continuation_gap"], -1e-10)

    def test_implicit_boundary_and_value_gradient_against_refitted_costs(self):
        problem, step = Problem(), 1e-5
        result = solve_boundary(problem)
        plus = solve_boundary(replace(problem, cost=problem.cost + step))
        minus = solve_boundary(replace(problem, cost=problem.cost - step))
        finite = np.array([plus.boundary - minus.boundary,
                           plus.value(problem.initial) - minus.value(problem.initial)]) / (2 * step)
        gradient = result.cost_derivative()
        np.testing.assert_allclose(
            [gradient["boundary"], gradient["initial_value"]], finite, rtol=0, atol=2e-8)

    def test_independent_finite_dp_error_decreases_with_grid_refinement(self):
        problem = Problem()
        reference, errors = solve_boundary(problem), []
        for nodes in (21, 41, 81):
            control = FiniteControl(replace(problem, nodes=nodes))
            solved = control.policy_iteration()
            errors.append(float(np.max(np.abs(solved["value"] - reference.value(control.x)))))
        self.assertTrue(all(a > b for a, b in zip(errors[:-1], errors[1:])), errors)

    def test_fixed_thresholds_and_unsupported_endpoint_regime(self):
        problem = Problem()
        optimum = solve_boundary(problem)
        points = np.linspace(0, problem.upper, 129)
        for boundary in (0.4, 0.9):
            fixed = fixed_threshold(problem, boundary)
            self.assertLess(abs(fixed.residuals()["value_matching"]), 1e-10)
            self.assertTrue(np.all(optimum.value(points) >= fixed.value(points) - 1e-10))
            with self.assertRaises(ValueError):
                fixed.cost_derivative()
        with self.assertRaisesRegex(ValueError, "no bracketed interior"):
            solve_boundary(replace(problem, cost=10))
