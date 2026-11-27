"""P0 fail-closed regression: very short first segments need standard-normal panels."""
import unittest
import mpmath as mp

from experiments.hcsn_hx_unified_v3.moving_boundary_enclosure import linear_boundary_first_hit
from experiments.hcsn_hx_unified_v3.piecewise_boundary_oracle import two_segment_first_hit


class NarrowSwitchQuadratureTests(unittest.TestCase):
    def test_discounted_unresolved_spatial_gaussian_is_no_longer_missed(self):
        # Physical error from the short first leg is O(1e-70). At dps=100,
        # the old unscaled-y quadrature returned a plausible but wrong result:
        # |delta F|=1.86e-15 and |delta G|=1.62e-15.
        switch = mp.mpf("1e-70")
        got = two_segment_first_hit(1, 0, 0, .5, 0, .8, switch, 1, .2, dps=100)
        limit = linear_boundary_first_hit(1, 0, 0, .5, .8, 1, .2, dps=100)
        for observed, reference in zip(got, limit):
            self.assertLess(abs(observed-reference), mp.mpf("1e-65"))
        self.assertLess(got.discounted, got.probability)

    def test_no_discount_narrow_switch_retains_physical_mass(self):
        # Original unscaled integral failed the bracket for 1e-40, while
        # 1e-70 could silently lose ~1.86e-15 of hitting probability.
        for exponent in (40, 70):
            with self.subTest(exponent=exponent):
                got = two_segment_first_hit(
                    1, 0, 0, .5, 0, .8, mp.mpf(10)**(-exponent), 1, 0, dps=60
                )
                limit = linear_boundary_first_hit(1, 0, 0, .5, .8, 1, 0, dps=75)
                self.assertEqual(got.probability, got.discounted)
                self.assertLess(abs(got.probability-limit.probability), mp.mpf('1e-35'))

    def test_normal_width_matches_previous_two_slope_reference(self):
        got = two_segment_first_hit(1, 0, 0, .4, .8, 0, .5, 1, .2, dps=80)
        self.assertLess(abs(got.probability-mp.mpf('0.13034319097200746')),
                        mp.mpf('1e-16'))
        self.assertLess(abs(got.discounted-mp.mpf('0.11371219839348145')),
                        mp.mpf('1e-16'))
        self.assertLess(got.discounted, got.probability)

    def test_very_short_nonzero_discount_remains_fail_closed_if_unresolved(self):
        # This patch does not relax the existing strict F/G check in the
        # *upstream* linear first-hit kernel for extreme short horizons.
        with self.assertRaises(ArithmeticError):
            two_segment_first_hit(1, 0, 0, .5, 0, .8,
                                  mp.mpf('1e-80'), 1, .2, dps=60)


if __name__ == '__main__':
    unittest.main()
