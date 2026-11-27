"""Focused checks for P0/P2 piecewise-barrier slope certificate."""
from fractions import Fraction
import math
import unittest

import mpmath as mp

from experiments.hcsn_hx_unified_v3.moving_boundary_enclosure import (
    linear_boundary_first_hit,
)
from experiments.hcsn_hx_unified_v3.piecewise_boundary_certificate import (
    certified_slope_bounds, piecewise_linear_first_hit_envelope,
)


class PiecewiseBoundaryCertificateTests(unittest.TestCase):
    def test_exact_constant_slope_matches_independent_linear_oracle(self):
        knots = ((0., .125), (.5, .375), (1., .625))
        got = piecewise_linear_first_hit_envelope(1.1, .12, .47, knots, .3, dps=100)
        self.assertEqual((got.lower_slope, got.upper_slope), (.5, .5))
        ref = linear_boundary_first_hit(1.1, .125, .12, .47, .5, 1., .3, dps=100)
        for a, b in ((got.lower.probability, ref.probability),
                     (got.upper.probability, ref.probability),
                     (got.lower.discounted, ref.discounted),
                     (got.upper.discounted, ref.discounted)):
            self.assertLess(abs(a-b), mp.mpf('1e-80'))

    def test_nonmonotone_slope_encloses_every_segment_exactly(self):
        knots = ((0., .15), (.25, .3), (.75, .05), (1., .2))
        lo, hi = certified_slope_bounds(knots)
        self.assertLess(lo, 0)
        self.assertGreater(hi, 0)
        for (ta, ba), (tb, bb) in zip(knots, knots[1:]):
            exact = ((Fraction.from_float(bb)-Fraction.from_float(ba)) /
                     (Fraction.from_float(tb)-Fraction.from_float(ta)))
            self.assertLessEqual(Fraction.from_float(lo), exact)
            self.assertGreaterEqual(Fraction.from_float(hi), exact)
        out = piecewise_linear_first_hit_envelope(.9, -.1, .36, knots, .15)
        self.assertLessEqual(out.lower.probability, out.upper.probability)
        self.assertLessEqual(out.lower.discounted, out.upper.discounted)
        self.assertLessEqual(out.lower.discounted, out.lower.probability)
        self.assertLessEqual(out.upper.discounted, out.upper.probability)

    def test_rational_outward_rounding_when_segment_slope_is_not_f64(self):
        knots = ((0., 0.), (.3, .1), (1., .3))
        a, b = certified_slope_bounds(knots)
        exact = [(Fraction.from_float(y2)-Fraction.from_float(y1)) /
                 (Fraction.from_float(t2)-Fraction.from_float(t1))
                 for (t1,y1),(t2,y2) in zip(knots,knots[1:])]
        self.assertLessEqual(Fraction.from_float(a), min(exact))
        self.assertGreaterEqual(Fraction.from_float(b), max(exact))
        self.assertTrue(any(Fraction.from_float(c) != e for c,e in zip((a,b),
                      (min(exact),max(exact)))))

    def test_one_ulp_time_intervals_use_exact_knot_differences(self):
        t1 = math.nextafter(1.0, math.inf)
        b1 = math.nextafter(.1, math.inf)
        knots = ((0.,0.),(1.,.1),(t1,b1))
        lo,hi = certified_slope_bounds(knots)
        tiny_interval_slope = ((Fraction.from_float(b1)-Fraction.from_float(.1)) /
                               (Fraction.from_float(t1)-Fraction.from_float(1.)))
        self.assertLessEqual(Fraction.from_float(lo), tiny_interval_slope)
        self.assertGreaterEqual(Fraction.from_float(hi), tiny_interval_slope)
        self.assertLessEqual(lo, hi)

    def test_positive_subnormal_slope_is_not_silently_zeroed(self):
        knots=((0., 0.), (1., math.ulp(0.)))
        lo,hi=certified_slope_bounds(knots)
        self.assertEqual((lo,hi),(math.ulp(0.),math.ulp(0.)))

    def test_overflowing_exact_slope_fails_closed(self):
        with self.assertRaises(ArithmeticError):
            certified_slope_bounds(((0.,-1e308),(1e-300,1e308)))

    def test_input_rejections_and_frozen_physics(self):
        bad=([], [(0.,0.)], ((1.,0.),(2.,1.)), ((0.,0.),(0.,1.)),
             ((0.,0.),(-1.,1.)), ((0.,0.),(math.inf,1.)),
             ((0.,0.),(1.,math.nan)), ((0.,0.),(1,1.)),
             ((False,0.),(1.,1.)), ((0.,0.,0.),(1.,1.)))
        for case in bad:
            with self.subTest(case=case), self.assertRaises(ValueError):
                certified_slope_bounds(case)
        with self.assertRaises(ValueError):
            piecewise_linear_first_hit_envelope(1.,0.,.2,((0.,0.),(1.,.5)),dps=49)
        with self.assertRaises(ValueError):
            piecewise_linear_first_hit_envelope(1.,0.,0.,((0.,0.),(1.,.5)))
        with self.assertRaises(ValueError):
            piecewise_linear_first_hit_envelope(1.,0.,.2,((0.,0.),(1.,.5)),q=-1)

    def test_pathwise_boundary_is_between_slope_lines(self):
        knots=((0.,-.2),(.25,.4),(.8,-.1),(1.1,.2))
        lo,hi=certified_slope_bounds(knots)
        for (ta,ba),(tb,bb) in zip(knots,knots[1:]):
            for j in range(101):
                # Compare exact rational interpolants, not f64 rounded paths.
                fa,fb = Fraction.from_float(ta),Fraction.from_float(tb)
                t=fa+(fb-fa)*j/100
                v=(Fraction.from_float(ba)+
                   (Fraction.from_float(bb)-Fraction.from_float(ba)) *
                   (t-fa)/(fb-fa))
                self.assertLessEqual(Fraction.from_float(knots[0][1])+
                                     Fraction.from_float(lo)*t,v)
                self.assertGreaterEqual(Fraction.from_float(knots[0][1])+
                                        Fraction.from_float(hi)*t,v)

    def test_absorbing_initial_condition_preserves_unit_first_hit(self):
        knots=((0.,.4),(.4,.3),(1.,.8))
        out=piecewise_linear_first_hit_envelope(.4,0.,.3,knots,.4)
        self.assertEqual((out.lower.probability,out.lower.discounted,
                          out.upper.probability,out.upper.discounted), (1,1,1,1))

    def test_invalid_large_knot_count_refuses(self):
        with self.assertRaises(ValueError):
            certified_slope_bounds([(float(i),float(i)) for i in range(4097)])


if __name__ == '__main__':
    unittest.main()
