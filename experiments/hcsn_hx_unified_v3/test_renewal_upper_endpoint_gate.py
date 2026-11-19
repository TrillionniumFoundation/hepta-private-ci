"""Fail-closed admission of the *interior* regenerative Lambert-W root.

Research-only f64 regression. Decimal is an independent root-level check;
this is not an interval certification of the coupled HX/QVI problem.
"""
from decimal import Decimal, localcontext
import math
import unittest

from scipy.special import lambertw

from .stopping import (Stop, one_shot_boundary, regenerative_boundary,
                       regenerative_boundary_independent, regenerative_obstacle,
                       regenerative_value, qvi)


def _case(h: float) -> Stop:
    # mu=0, sigma=1, rho=1/2 => kappa=1 and h=cost-reset.
    return Stop(0.0, 1.0, 0.5, 0.0, -h, 0.0)


class RenewalUpperEndpointTests(unittest.TestCase):
    def test_finite_loss_with_binary64_endpoint_saturation_is_refused(self):
        # On the unpatched source every primary call below returns exactly
        # the one-shot limit b=1 while the strict renewal root satisfies t<1.
        for h in (37.0, 40.0, 50.0, 100.0, 710.0):
            with self.subTest(h=h):
                p=_case(h)
                self.assertEqual(p.kappa, 1.0)
                raw=1+float(lambertw(-math.exp(-h)/math.e,k=0).real)
                self.assertEqual(raw,1.0)
                self.assertEqual(one_shot_boundary(p),1.0)
                with self.assertRaisesRegex(ArithmeticError, 'inside'):
                    regenerative_boundary(p)
                # The existing independent Brent solver refuses this same
                # unresolved upper endpoint; keep both oracles aligned.
                with self.assertRaises(ArithmeticError):
                    regenerative_boundary_independent(p)

    def test_independent_high_precision_root_is_not_at_endpoint(self):
        with localcontext() as ctx:
            ctx.prec=150
            half_ulp=Decimal.from_float(math.ulp(1.0))/2
            for h in (37.0,40.0,50.0,100.0):
                with self.subTest(h=h):
                    hd=Decimal.from_float(h)
                    # Let s=1-t; exact exponential smooth-fit:
                    # s=exp(-h-1+s). Positive fixed-point contraction.
                    s=(-(hd+1)).exp()
                    for _ in range(12):
                        s=(-(hd+1)+s).exp()
                    t=Decimal(1)-s
                    self.assertTrue(Decimal(0)<t<Decimal(1))
                    self.assertTrue(Decimal(0)<s<half_ulp)
                    self.assertLess(abs(t+(-hd-t).exp()-1),
                                    Decimal('1e-90'))

    def test_resolvable_regular_branches_remain_admitted_and_monotone(self):
        old=0.0
        for h in (1e-3,.01,.1,.5,1.,5.,10.,20.,30.,36.):
            with self.subTest(h=h):
                p=_case(h)
                b=regenerative_boundary(p)
                self.assertTrue(0<b<one_shot_boundary(p))
                self.assertGreater(b,old)
                old=b
                if h<=10.:
                    self.assertLess(abs(b-regenerative_boundary_independent(p)),
                                    3e-10)

    def test_implicit_value_obstacle_and_qvi_cannot_bypass_refusal(self):
        p=_case(40.)
        for op in (lambda: regenerative_value(p,p.reset),
                   lambda: regenerative_obstacle(p,p.reset),
                   lambda: qvi(p,p.reset)):
            with self.subTest(op=op),self.assertRaises(ArithmeticError):
                op()


if __name__=='__main__':
    unittest.main()
