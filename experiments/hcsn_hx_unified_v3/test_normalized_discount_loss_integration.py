"""P0 composed physical-invariant gate for normalized two-segment first-hit.

Research only. This tests a necessary mathematical envelope, not a
certified interval quadrature, complete He-Xiong equilibrium, or deployment.
"""
import unittest
import mpmath as mp
from .moving_boundary_enclosure import linear_boundary_first_hit as linear
from .piecewise_boundary_oracle import two_segment_first_hit as piecewise


class DiscountLossCompositionTests(unittest.TestCase):
    def test_linear_equal_discount_loss_must_refuse(self):
        with self.assertRaisesRegex(ArithmeticError, "unresolved discounted first-hit loss"):
            linear(1, 0, 0, .6, 0, 1.3, mp.mpf('1e-200'), dps=65)

    def test_linear_spurious_oversized_discount_loss_must_refuse(self):
        with self.assertRaisesRegex(ArithmeticError, "unresolved discounted first-hit loss"):
            linear(1, 0, 0, .6, 0, 1.3, mp.mpf('1e-90'), dps=65)

    def test_piecewise_normalized_gap_equal_discount_loss_must_refuse(self):
        for q in (mp.mpf('1e-90'), mp.mpf('1e-200')):
            with self.subTest(q=str(q)):
                with self.assertRaisesRegex(ArithmeticError, "discount.*loss"):
                    piecewise(1, 0, 0, .6, -.2, .7, .6, 1.3, q, dps=60)

    def test_zero_length_segment_fallback_cannot_bypass_discount_gate(self):
        for switch in (0, 1.3):
            with self.subTest(switch=switch):
                with self.assertRaisesRegex(ArithmeticError, "unresolved discounted first-hit loss"):
                    piecewise(1, 0, 0, .6, 0, 0, switch, 1.3,
                              mp.mpf('1e-200'), dps=60)

    def test_ordinary_positive_discount_satisfies_exact_necessary_envelope(self):
        for q in (mp.mpf('.01'), mp.mpf('.2')):
            with self.subTest(q=str(q)):
                a = linear(1,0,0,.6,0,1.3,q,dps=100)
                b = piecewise(1,0,0,.6,-.2,.7,.6,1.3,q,dps=75)
                with mp.workdps(140):
                    for f in (a,b):
                        loss = f.probability-f.discounted
                        upper = f.probability*(-mp.expm1(-q*mp.mpf('1.3')))
                        self.assertTrue(0 < f.discounted < f.probability < 1)
                        self.assertTrue(0 < loss < upper)

    def test_no_discount_and_immediate_hit_are_exact_degeneracies(self):
        for f in (linear(1,0,0,.6,0,1.3,0,dps=65),
                  piecewise(1,0,0,.6,-.2,.7,.6,1.3,0,dps=60)):
            self.assertEqual(f.probability, f.discounted)
        self.assertEqual(linear(0,0,0,.6,0,1.3,.2).probability, 1)
        self.assertEqual(linear(0,0,0,.6,0,1.3,.2).discounted, 1)
        self.assertEqual(piecewise(0,0,0,.6,-.2,.7,.6,1.3,.2).probability, 1)
        self.assertEqual(piecewise(0,0,0,.6,-.2,.7,.6,1.3,.2).discounted, 1)

    def test_narrow_mode_normalization_remains_admitted_at_q_zero(self):
        # End position at time 1 equals moving boundary plus sigma*W_1.
        # Thus the first-hit probability is at least 1/2 by continuity.
        out = piecewise(1, 0, 4, '1e-24', 0, 10, '.5', 1, 0, dps=50)
        with mp.workdps(85):
            self.assertGreaterEqual(out.probability, mp.mpf('.5'))
            self.assertLess(out.probability-mp.mpf('.5'), mp.mpf('1e-18'))
            self.assertEqual(out.discounted, out.probability)

    def test_piecewise_physically_valid_zero_horizon(self):
        out = piecewise(1, 0, 0, .6, -.2, .7, 0, 0, .2, dps=60)
        self.assertEqual(out.probability, 0)
        self.assertEqual(out.discounted, 0)


if __name__ == '__main__':
    unittest.main()
