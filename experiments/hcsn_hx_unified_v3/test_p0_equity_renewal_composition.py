"""P0 safety composition across stacked He--Xiong and renewal research branches.

These are source-importing regressions. They do not certify a coupled HX
obstacle solution, f32 gradients, numerical intervals, or deployment readiness.
"""
import math
import unittest

from scipy.special import lambertw

from .hx import HX, bond_value, equity_closed
from .stopping import (Stop, one_shot_boundary, regenerative_boundary,
                       regenerative_boundary_independent,
                       regenerative_obstacle, regenerative_value, qvi)


class P0CompositionTests(unittest.TestCase):
    def test_extreme_finite_equity_ratio_does_not_propagate_nan(self):
        p = HX()
        for asset, barrier in ((1e308, 1e-308), (1e308, 1e-100),
                               (1e200, 1e-200)):
            with self.subTest(asset=asset, barrier=barrier):
                self.assertTrue(math.isinf(asset / barrier))
                value = equity_closed(p, asset, barrier)
                self.assertTrue(math.isfinite(value))
                self.assertGreater(value, 0.)

    def test_ordinary_financial_equity_remains_finite(self):
        p = HX()
        for asset, barrier in ((100., 50.), (130., 64.), (180., 70.)):
            with self.subTest(asset=asset, barrier=barrier):
                self.assertTrue(math.isfinite(equity_closed(p, asset, barrier)))

    def test_small_discount_bond_fix_remains_present(self):
        p = HX(rate=1e-16, shock_intensity=0., sale_fraction=0.)
        self.assertNotEqual(math.exp(-p.q), 1.)
        self.assertAlmostEqual(bond_value(p, 1e100, 1., 1.), 32., delta=1e-12)

    def test_roundoff_endpoint_does_not_become_legal_threshold(self):
        for h in (37., 40., 50., 100., 710.):
            with self.subTest(h=h):
                p = Stop(0., 1., .5, 0., -h, 0.)
                self.assertAlmostEqual(p.kappa, 1., delta=5e-16)
                self.assertEqual(1 + float(lambertw(-math.exp(-h)/math.e).real), 1.)
                self.assertAlmostEqual(one_shot_boundary(p), 1., delta=5e-16)
                with self.assertRaisesRegex(ArithmeticError, 'inside'):
                    regenerative_boundary(p)
                with self.assertRaises(ArithmeticError):
                    regenerative_boundary_independent(p)

    def test_saturation_failure_propagates_to_value_obstacle_and_qvi(self):
        p = Stop(0., 1., .5, 0., -40., 0.)
        for fn in (lambda: regenerative_value(p, -40.),
                   lambda: regenerative_obstacle(p, -40.),
                   lambda: qvi(p, -40.)):
            with self.subTest(fn=fn), self.assertRaises(ArithmeticError):
                fn()

    def test_regular_interior_roots_are_still_admitted(self):
        last = 0.
        for h in (1e-3, 1e-2, .1, .5, 1., 5., 10., 20., 30.):
            with self.subTest(h=h):
                p = Stop(0., 1., .5, 0., -h, 0.)
                b = regenerative_boundary(p)
                self.assertTrue(last < b < one_shot_boundary(p))
                last = b
                if h <= 10.:
                    self.assertLess(abs(b-regenerative_boundary_independent(p)), 3e-10)


if __name__ == '__main__':
    unittest.main()
