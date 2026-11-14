"""P0 independent scalar stopping smooth-fit oracle branch-point regression.

Research only: local f64 threshold/Decimal equation checks, not financial HX
coupled equilibrium, global QVI, native low-precision or production admission.
"""

from dataclasses import replace
import math
import random
import unittest

from .stopping import Stop, regenerative_boundary, regenerative_boundary_independent
from .test_stop_branchpoint import high_precision_boundary


class IndependentSmoothfitGateTests(unittest.TestCase):
    def assert_independent_root(self, p, rel=4e-12):
        got=regenerative_boundary_independent(p)
        want=high_precision_boundary(p)
        self.assertTrue(math.isfinite(got) and got>p.cost)
        self.assertLessEqual(abs(got-want), rel*max(abs(want-p.cost), 1e-300),
                             (p, got, want))
        self.assertLessEqual(abs(got-regenerative_boundary(p)),
                             rel*max(abs(want-p.cost), 1e-300), (p, got, want))

    def test_exact_old_brent_zero_bracket_witness(self):
        # Old direct exp(-h)-1 rounds to 0: left endpoint is falsely a root.
        p=Stop(0.,1.,.5,0.,-1e-20,0.)
        self.assert_independent_root(p)

    def test_exact_old_brent_massive_relative_error_witness(self):
        # Prior Brent returned ~3.5e-13 instead of ~1.414e-8.
        p=Stop(0.,1.,.5,0.,-1e-16,0.)
        self.assert_independent_root(p)

    def test_branch_point_and_subnormal_loss_panel(self):
        for gap in (1e-12,1e-14,1e-16,1e-20,1e-40,1e-100,1e-200,1e-300):
            with self.subTest(gap=gap):
                self.assert_independent_root(Stop(0.,1.,.5,0.,-gap,0.))

    def test_discounted_refractory_and_reset_are_both_included(self):
        p=Stop(0.,1.,.5,0.,-1e-20,1e-20)
        self.assert_independent_root(p)
        self.assertGreater(regenerative_boundary_independent(p),
                           regenerative_boundary_independent(replace(p,refractory=0.)))

    def test_nominal_existing_oracles_remain_aligned(self):
        cases=(Stop(.1,.4,.1,1.,0.,.3),Stop(-.3,1.,.01,.4,-1.,1.),
               Stop(.5,.05,1.,1.,0.,0.),Stop(0.,.6,.5,1.,0.,2.))
        for p in cases:
            with self.subTest(p=p):
                self.assertLess(abs(regenerative_boundary_independent(p)
                                    -regenerative_boundary(p)),1e-10)

    def test_erased_cost_boundary_must_be_refused(self):
        p=Stop(0.,1.,.5,1e308,0.,0.)
        with self.assertRaises(ArithmeticError):
            regenerative_boundary_independent(p)

    def test_explicit_unresolvable_delay_refuses(self):
        p=Stop(0.,1.,1e-200,0.,-1.,1e-200)
        with self.assertRaises(ArithmeticError):
            regenerative_boundary_independent(p)

    def test_seeded_tiny_loss_against_existing_independent_decimal_root(self):
        rng=random.Random(2026103147)
        k=Stop(0.,1.,.5,0.,-1.,0.).kappa
        for i in range(48):
            h=10**rng.uniform(-290.,-4.1)
            p=Stop(0.,1.,.5,0.,-h/k,0.)
            with self.subTest(i=i,h=h):
                self.assert_independent_root(p,rel=5e-12)


if __name__=='__main__':
    unittest.main()
