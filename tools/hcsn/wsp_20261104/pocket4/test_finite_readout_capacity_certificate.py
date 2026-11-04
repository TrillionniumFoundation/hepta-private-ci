"""Synthetic mathematical edge cases; no private input is needed."""
from fractions import Fraction
import unittest

import numpy as np

from finite_readout_capacity_certificate import certificate, integer_root_floor, root_grid_bounds


class CapacityCertificateTests(unittest.TestCase):
    def test_integer_root_rounds_down_for_large_nonperfect_power(self):
        base = 10 ** 40 + 12345
        for degree in (2, 16, 32):
            self.assertEqual(integer_root_floor(base ** degree, degree), base)
            self.assertEqual(integer_root_floor(base ** degree - 1, degree), base - 1)

    def test_rational_root_enclosure_is_exactly_outward(self):
        for number, degree in ((Fraction(2), 2), (Fraction(4, 9), 2), (Fraction(1, 10 ** 100), 32)):
            low, high = root_grid_bounds(number, degree, digits=24)
            self.assertLessEqual(Fraction(low, 10 ** 24) ** degree, number)
            self.assertGreaterEqual(Fraction(high, 10 ** 24) ** degree, number)
            self.assertLessEqual(high - low, 1)

    def test_rank_one_bound_and_translation_invariance(self):
        x = np.array([[-1.0], [1.0]])
        y = np.array([-10.0, 10.0])
        original = certificate(x, y, Fraction(1), Fraction(1))
        translated = certificate(x + 100000.0, y + 42.0, Fraction(1), Fraction(1))
        for report in (original, translated):
            self.assertEqual(Fraction(report["certified_prediction_sd_upper_bound_usd"]), 1)
            self.assertEqual(Fraction(report["certified_rmse_lower_bound_usd"]), 9)

    def test_constant_features_cannot_remove_target_variance(self):
        report = certificate(np.full((2, 3), 7.0), np.array([-10.0, 10.0]))
        self.assertEqual(Fraction(report["certified_prediction_sd_upper_bound_usd"]), 0)
        self.assertEqual(Fraction(report["certified_rmse_lower_bound_usd"]), 10)

    def test_clipping_variance_uses_pairwise_not_fixed_zero_mean(self):
        values = np.array([-40.0, -7.0, 20.0, 70.0, 130.0])
        clipped = np.clip(values, -15, 15)
        pairwise_variance = np.square(clipped[:, None] - clipped[None, :]).sum() / (2 * len(values) ** 2)
        self.assertAlmostEqual(pairwise_variance, np.var(clipped, ddof=0))
        self.assertLessEqual(pairwise_variance, np.var(values, ddof=0))


if __name__ == "__main__":
    unittest.main()
