"""Numerical gradients, independent simulation and intervention semantics."""

import unittest

import numpy as np
from scipy.optimize import check_grad, minimize

from . import joint_model as joint
from . import ordinary
from .campaign import make_data
from .simulator import Physics, sample_counts


class JointChecks(unittest.TestCase):
    def test_joint_likelihood_gradient_by_independent_finite_difference(self):
        data = make_data(10009, 27)
        theta = np.array([.07, -.06, .9, -2.1, -1.7, .6])
        for mode in joint.MODES:
            args = (data["packets"], data["delta_labels"], mode, .001)
            error = check_grad(lambda v: joint.objective(v, *args)[0],
                               lambda v: joint.objective(v, *args)[1], theta)
            self.assertLess(error, 2e-5, mode)

    def test_ordinary_mlp_gradient_by_finite_difference(self):
        rng = np.random.default_rng(102)
        x, y = rng.normal(size=(9, 6)), rng.integers(5, size=9)
        initial = ordinary.initialize(103)
        error = check_grad(lambda v: ordinary.objective(v, x, y, .001)[0],
                           lambda v: ordinary.objective(v, x, y, .001)[1], initial)
        self.assertLess(error, 2e-6)

    def test_joint_fit_changes_dynamics_and_content_and_reduces_loss(self):
        data = make_data(221, 128)
        initial = np.zeros(6)
        args = (data["packets"], data["delta_labels"], "original", .001)
        initial_loss, gradient = joint.objective(initial, *args)
        self.assertGreater(float(np.linalg.norm(gradient[:2])), 1e-4)
        self.assertGreater(float(np.linalg.norm(gradient[2:])), 1e-4)
        result = minimize(joint.objective, initial, args=args, jac=True,
            method="L-BFGS-B", bounds=[(-.5,.5)]*2+[(-8,8)]*4, options={"maxiter": 40})
        self.assertLess(result.fun, initial_loss-.001)
        self.assertGreater(float(np.linalg.norm(result.x[:2]-initial[:2])), 1e-3)
        self.assertGreater(float(np.linalg.norm(result.x[2:]-initial[2:])), 1e-3)

    def test_single_mode_executes_exactly_one_learned_content_transition(self):
        data = make_data(811, 17)
        theta = np.array([.2, -.1, 1.2, -2, -3, .7])
        counts, gradient = joint.count_law(theta, data["packets"], "single_transition")
        np.testing.assert_array_equal(counts[:,2:], 0)
        np.testing.assert_array_equal(gradient[:,2:], 0)
        _, _, weights = joint.content_powers(theta)
        expected = counts[:,0,None]*np.eye(5)[0]+counts[:,1,None]*weights
        actual, _ = joint.predict(theta, data["packets"], "single_transition")
        np.testing.assert_allclose(actual, expected, atol=1e-14)

    def test_mean_shape_and_probability_gradients_preserve_declared_mass(self):
        data = make_data(112, 37)
        theta = np.array([.15, -.15, 1.2, -2, -3, .7])
        full, _ = joint.count_law(theta, data["packets"], "original")
        mean, _ = joint.count_law(theta, data["packets"], "mean_two_point")
        np.testing.assert_allclose(full@np.arange(joint.CAP), mean@np.arange(joint.CAP), atol=1e-12)
        for mode in joint.MODES:
            p, dp = joint.predict(theta, data["packets"], mode)
            self.assertTrue(np.isfinite(p).all() and np.isfinite(dp).all())
            self.assertGreaterEqual(float(p.min()), 0)
            np.testing.assert_allclose(p.sum(1), 1, atol=1e-12)
            np.testing.assert_allclose(dp.sum(1), 0, atol=1e-9)

    def test_independent_ig_counts_match_joint_count_law(self):
        physics = Physics(-.8, .55, .45, .18)
        packet = np.array([[.15, 2.4, physics.nu, physics.sigma, physics.reset, physics.refractory]])
        p, _ = joint.count_law(np.zeros(6), packet, "original")
        counts = sample_counts(np.random.default_rng(443), physics, .15, 2.4, 20000)
        empirical = np.bincount(counts, minlength=joint.CAP)/len(counts)
        tolerance = 5*np.sqrt(np.maximum(p[0]*(1-p[0]), 1/len(counts))/len(counts))
        self.assertTrue(np.all(np.abs(empirical-p[0]) <= tolerance))


if __name__ == "__main__":
    unittest.main()
