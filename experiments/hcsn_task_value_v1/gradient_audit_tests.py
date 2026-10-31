"""Audit-tool controls: smooth functions, wrong derivatives and actual kinks."""

import math
import unittest

import numpy as np

from .gradient_audit import directional_audit


class GradientAuditControlTests(unittest.TestCase):
    def test_smooth_vector_and_curvature_pass(self):
        value = lambda t: np.array([math.exp(t), t*t, math.sin(2*t)])
        result = directional_audit(value, np.array([1., 0., 2.]))
        self.assertTrue(result['passed'])
        self.assertEqual(result['persistent_jump_components'], 0)

    def test_wrong_gradient_is_not_accepted(self):
        result = directional_audit(lambda t: np.array([2*t]), np.array([1.]))
        self.assertFalse(result['passed'])
        self.assertGreater(result['max_derivative_error'], 0.99)

    def test_central_average_at_cusp_does_not_certify_derivative(self):
        result = directional_audit(lambda t: np.array([abs(t)]), np.array([0.]))
        self.assertEqual(result['max_derivative_error'], 0.0)
        self.assertFalse(result['passed'])
        self.assertEqual(result['persistent_jump_components'], 1)

    def test_tied_actions_with_identical_derivative_can_pass(self):
        value = lambda t: np.array([max(2*t+t*t, 2*t-t*t)])
        result = directional_audit(value, np.array([2.]))
        self.assertTrue(result['passed'])

    def test_nonfinite_or_shape_changing_callback_is_rejected(self):
        for value in (lambda t: np.array([math.nan]),
                      lambda t: np.zeros(1 if t == 0 else 2)):
            with self.assertRaises(ValueError):
                directional_audit(value, np.array([0.]))

    def test_unresolvable_step_is_rejected(self):
        with self.assertRaises(ValueError):
            directional_audit(lambda t: t, 1., at=1e20, step=1.)

    def test_finite_values_with_overflowed_quotients_are_rejected(self):
        with np.errstate(over='ignore', invalid='ignore'), self.assertRaises(ArithmeticError):
            directional_audit(lambda t: np.array([math.copysign(1e308, t)]),
                              np.array([0.]))


if __name__ == '__main__':
    unittest.main()
