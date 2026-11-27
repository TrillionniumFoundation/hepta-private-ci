"""Independent high-precision P0 regression for scalar renewal's W branch point.

Research-only. Verifies only finite, well-resolved Brownian scalar threshold
and QVI subdomains; never implies financial HX or production admission.
"""
from dataclasses import replace
from decimal import Decimal, localcontext
import math
import random
import unittest

from .stopping import Stop, regenerative_boundary, regenerative_boundary_independent
from .stopping import one_shot_boundary, qvi, regenerative_value


def high_precision_boundary(p: Stop) -> float:
    """Independent Decimal root of log smooth-fit, not scipy Lambert-W.

    Decimal.from_float uses the actual binary64 inputs, not rounded literals.
    This is intentionally costly and never used by a production kernel.
    """
    with localcontext() as ctx:
        ctx.prec=320
        d=lambda v: Decimal.from_float(v)
        mu,sigma,rho=d(p.drift),d(p.diffusion),d(p.discount)
        scale=(mu*mu+2*rho*sigma*sigma).sqrt()
        k=(scale-mu)/(sigma*sigma)
        h=k*(d(p.cost)-d(p.reset))+rho*d(p.refractory)
        if not h>0:
            raise AssertionError('invalid independent oracle setup')
        t=(2*h).sqrt() if h<Decimal("0.5") else 1-(-h-1).exp()
        for _ in range(35):
            # F(t)=-ln(1-t)-t-h; Decimal keeps tiny 1-t differences.
            err=-(1-t).ln()-t-h
            delta=err*(1-t)/t
            t-=delta
            if abs(delta)<Decimal('1e-300'):
                break
        # Cross-check the *other*, exponential smooth-fit formulation.
        residual=t+(-h-t).exp()-1
        assert abs(residual)<Decimal('1e-260')
        return float(d(p.cost)+t/k)


class RenewalBranchPointTests(unittest.TestCase):
    def test_old_exp_rounding_witness_matches_independent_320_digit_root(self):
        for gap in (1e-8,1e-12,1e-14,1e-16,1e-20,1e-40,1e-100,1e-200):
            with self.subTest(gap=gap):
                p=Stop(0.,1.,.1,0.,-gap,0.)
                b=regenerative_boundary(p)
                oracle=high_precision_boundary(p)
                self.assertTrue(math.isfinite(b) and b>p.cost)
                self.assertLessEqual(abs(b-oracle),3e-13*max(abs(oracle),1e-300),
                                     (gap,b,oracle))

    def test_refractory_and_reset_loss_are_both_counted(self):
        p=Stop(0.,1.,.1,0.,-1e-16,1e-16)
        b=regenerative_boundary(p)
        oracle=high_precision_boundary(p)
        self.assertLessEqual(abs(b-oracle),3e-13*abs(oracle))
        self.assertGreater(b,regenerative_boundary(replace(p,refractory=0)))
        self.assertGreater(b,regenerative_boundary(replace(p,reset=-1e-20)))

    def test_transition_to_regular_lambert_is_continuous(self):
        k=Stop(0.,1.,.1,0.,-1.,0.).kappa
        for h in (9.99e-5,1e-4,1.001e-4,1.1e-4,1e-2,.3,10.):
            p=Stop(0.,1.,.1,0.,-h/k,0.)
            got=regenerative_boundary(p)
            want=high_precision_boundary(p)
            self.assertLessEqual(abs(got-want),1e-11*max(want,1e-300),(h,got,want))

    def test_existing_regimes_keep_qvi_and_independent_root(self):
        cases=(Stop(.1,.4,.1,1,0,.3),Stop(-.3,1,.01,.4,-1,1),
               Stop(.5,.05,1,1,0,0),Stop(0,.6,.5,1,0,2))
        for p in cases:
            b=regenerative_boundary(p)
            self.assertLess(abs(b-regenerative_boundary_independent(p)),1e-10)
            self.assertLess(abs(b-high_precision_boundary(p)),1e-11)
            self.assertLessEqual(b,one_shot_boundary(p)+1e-10)
            for x in (p.reset,b-.1,b,b+.1):
                r=qvi(p,x)
                self.assertLessEqual(r['obstacle'],1e-9)
                self.assertLessEqual(r['generator'],1e-9)
                self.assertLessEqual(abs(r['complementarity']),1e-9)
                self.assertGreaterEqual(regenerative_value(p,x),-1e-12)

    def test_strict_boundary_monotonicity_across_small_loss(self):
        prev=0.
        for e in range(-200,-5,5):
            b=regenerative_boundary(Stop(0.,1.,.1,0.,-10.**e,0.))
            self.assertGreater(b,prev)
            prev=b

    def test_seeded_96_case_log_loss_panel(self):
        rng=random.Random(20261031)
        k=Stop(0.,1.,.1,0.,-1.,0.).kappa
        for index in range(96):
            h=10**rng.uniform(-290,2)
            p=Stop(0.,1.,.1,0.,-h/k,0.)
            actual=regenerative_boundary(p)
            oracle=high_precision_boundary(p)
            with self.subTest(index=index, h=h):
                self.assertLessEqual(abs(actual-oracle)/oracle,1e-12)

    def test_branchpoint_gradient_diverges_with_verified_finite_differences(self):
        # Exact smooth fit: db/dreset=-(1-t)/t and
        # db/drefractory=(rho/kappa)*(1-t)/t. As h -> 0+ the
        # Jacobian is intrinsically singular, not a solver regression.
        previous_magnitude=0.
        for gap in (1e-8,1e-12,1e-20,1e-40,1e-100):
            p=Stop(0.,1.,.1,0.,-gap,0.)
            b=regenerative_boundary(p)
            t=p.kappa*(b-p.cost)
            predicted=-(1-t)/t
            epsilon=gap*1e-4
            plus=regenerative_boundary(replace(p,reset=p.reset+epsilon))
            minus=regenerative_boundary(replace(p,reset=p.reset-epsilon))
            numerical=(plus-minus)/(2*epsilon)
            self.assertLess(abs(numerical-predicted)/abs(predicted),2e-8)
            self.assertGreater(abs(predicted),previous_magnitude)
            previous_magnitude=abs(predicted)
        p=Stop(0.,1.,.1,0.,-1e-12,1e-12)
        b=regenerative_boundary(p)
        t=p.kappa*b
        predicted=p.discount/p.kappa*(1-t)/t
        epsilon=1e-16
        plus=regenerative_boundary(replace(p,refractory=p.refractory+epsilon))
        minus=regenerative_boundary(replace(p,refractory=p.refractory-epsilon))
        numerical=(plus-minus)/(2*epsilon)
        self.assertLess(abs(numerical-predicted)/predicted,2e-8)

    def test_fail_closed_on_erased_or_unresolved_transforms(self):
        cases=(Stop(0.,1.,.1,0.,-float.fromhex('0x0.0000000000001p-1022'),0.),
               Stop(1e200,1e-200,1e-200,0.,-1.,0.),
               Stop(0.,1.,.1,1e308,-1e308,0.),
               Stop(0.,1.,1e-200,0.,-1.,1e-200))
        for p in cases:
            with self.subTest(p=p),self.assertRaises(ArithmeticError):
                regenerative_boundary(p)


if __name__=='__main__':
    unittest.main()
