"""Discount-loss admission must detect f64/mpf significance loss (research)."""
import unittest

import mpmath as mp

from experiments.hcsn_hx_unified_v3.moving_boundary_enclosure import linear_boundary_first_hit
from experiments.hcsn_hx_unified_v3.piecewise_boundary_oracle import two_segment_first_hit


class DiscountLossAdmissionTests(unittest.TestCase):
    def test_linear_tiny_discount_strict_positive_loss_refused(self):
        # With a positive gap and q, exact F-G>0. At 65 dps it rounds to 0.
        with self.assertRaisesRegex(ArithmeticError, "discounted first-hit loss"):
            linear_boundary_first_hit(1, 0, 0, .6, 0, 1.3,
                                      mp.mpf('1e-200'), dps=65)

    def test_linear_false_oversized_loss_refused(self):
        # At 65 dps, cancellation yields apparent D about 3e-67,
        # exceeding the rigorous upper bound q*T*F ~ 1e-90.
        with self.assertRaisesRegex(ArithmeticError, "discounted first-hit loss"):
            linear_boundary_first_hit(1, 0, 0, .6, 0, 1.3,
                                      mp.mpf('1e-90'), dps=65)

    def test_piecewise_tiny_discount_strict_positive_loss_refused(self):
        for q in (mp.mpf('1e-90'), mp.mpf('1e-200')):
            with self.subTest(q=str(q)):
                with self.assertRaisesRegex(ArithmeticError, "discount.*loss"):
                    two_segment_first_hit(1, 0, 0, .6, -.2, .7, .6, 1.3,
                                          q, dps=50)

    def test_independent_mathematical_positive_lower_bound(self):
        # This physical bound is independent of the discounted quadrature:
        # Brownian paths first hitting after s/2 have strictly positive mass.
        # The lower bound on F-G remains positive even at q=1e-200.
        full_probability = two_segment_first_hit(1, 0, 0, .6, -.2, .7,
                                                  .6, 1.3, 0, dps=60).probability
        early_probability = linear_boundary_first_hit(1, 0, 0, .6, -.2,
                                                      .3, 0, dps=80).probability
        with mp.workdps(140):
            q = mp.mpf('1e-200')
            late_mass = full_probability - early_probability
            self.assertGreater(late_mass, mp.mpf('.01'))
            lower_loss = late_mass * (-mp.expm1(-q*mp.mpf('.3')))
            self.assertGreater(lower_loss, 0)
            self.assertLess(lower_loss, full_probability*(-mp.expm1(-q*mp.mpf('1.3'))))

    def test_ordinary_and_qzero_remain_admitted(self):
        for q in (0, mp.mpf('.01'), mp.mpf('.2')):
            with self.subTest(q=str(q)):
                f = linear_boundary_first_hit(1, 0, 0, .6, 0, 1.3, q, dps=80)
                v = two_segment_first_hit(1, 0, 0, .6, -.2, .7, .6, 1.3, q, dps=60)
                self.assertTrue(0 <= f.discounted <= f.probability <= 1)
                self.assertTrue(0 <= v.discounted <= v.probability <= 1)
                if q > 0:
                    self.assertGreater(f.probability, f.discounted)
                    self.assertGreater(v.probability, v.discounted)
                else:
                    self.assertEqual(f.probability, f.discounted)
                    self.assertEqual(v.probability, v.discounted)

    def test_immediate_or_zero_window_not_falsely_rejected(self):
        self.assertEqual(linear_boundary_first_hit(0, 0, 0, .6, 0, 1.3, .3), (1, 1))
        self.assertEqual(two_segment_first_hit(0, 0, 0, .6, -.2, .7, .6, 1.3, .3), (1, 1))
        self.assertEqual(linear_boundary_first_hit(1, 0, 0, .6, 0, 0, .3), (0, 0))
        self.assertEqual(two_segment_first_hit(1, 0, 0, .6, -.2, .7, 0, 0, .3), (0, 0))


if __name__ == '__main__':
    unittest.main()
