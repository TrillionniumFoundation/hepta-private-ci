"""Mathematical and interface regressions against independent high precision."""

import unittest
import numpy as np

import kernel
import reference


class FullKernelTests(unittest.TestCase):
    def test_boundary_double_zero_and_risk_right_derivative(self):
        value, jac = kernel.evaluate(kernel.BASE, 0., coordinate="log_distance")
        self.assertEqual(value[1], 0.)
        self.assertEqual(jac[1, -1], 0.)
        self.assertAlmostEqual(value[2], 1.)
        self.assertLess(jac[2, -1], 0.)
        below, below_jac = kernel.evaluate(kernel.BASE, value[0] * (1 - 1e-6))
        self.assertEqual(below[2], 1.)
        self.assertEqual(below_jac[2, -1], 0.)

    def test_fixed_asset_gradient_includes_moving_boundary(self):
        values, jac = kernel.evaluate(kernel.BASE, 100.)
        x = np.log(100. / values[0])
        _, fixed_x = kernel.evaluate(kernel.BASE, x, coordinate="log_distance")
        chain = fixed_x[1, :9] - fixed_x[1, -1] / values[0] * fixed_x[0, :9]
        np.testing.assert_allclose(jac[1, :9], chain, rtol=2e-11, atol=2e-11)
        np.testing.assert_allclose(jac, reference.jacobian(kernel.BASE, 100.), rtol=2e-9, atol=2e-9)

    def test_joint_short_maturity_low_liquidity_blend(self):
        theta = kernel.BASE.copy()
        theta[5], theta[6] = 1e-4, .01
        for x in (1.725e-5, .00023, .000345, .00046):
            actual, jac = kernel.evaluate(theta, x, coordinate="log_distance")
            ref = np.asarray(reference.fields(theta, x, "log_distance"), float)
            ref_jac = reference.jacobian(theta, x, "log_distance")
            self.assertLess(np.max(abs(actual - ref) / np.maximum(1., abs(ref))), 2e-8)
            self.assertLess(np.max(abs(jac - ref_jac) / np.maximum(1., abs(ref_jac))), 2e-5)

    def test_mixed_cast_backward_and_rejected_extreme(self):
        _, jac = kernel.evaluate(kernel.BASE, 100., mode="mixed32")
        theta = kernel.BASE.astype(np.float32).astype(float)
        ref = reference.jacobian(theta, 100.)
        self.assertEqual(jac.dtype, np.float32)
        self.assertLess(np.max(abs(jac - ref) / np.maximum(1., abs(ref))), 2e-5)
        theta[5] = 0.
        with self.assertRaises(ValueError):
            kernel.evaluate(theta, 100., mode="mixed32")


if __name__ == "__main__":
    unittest.main()
