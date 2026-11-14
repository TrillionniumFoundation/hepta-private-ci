import math
import random
import unittest
import mpmath as mp
from .coupon_focus import Inputs, parent_coupon, fixed_coupon

mp.mp.dps=100

def no_hit_oracle(p: Inputs,tau:float)->float:
    q=mp.mpf(p.q); t=mp.mpf(tau)
    return float(mp.mpf(p.per_bond_principal)*mp.exp(-q*t)
                 +mp.mpf(p.per_bond_coupon)*(-mp.expm1(-q*t))/q)

class CouponFocusedTests(unittest.TestCase):
    def test_reproduced_parent_wrong_nonunity_rounding(self):
        p=Inputs(30.,2.,1e-16)
        self.assertNotEqual(math.exp(-p.q),1.)
        self.assertEqual(parent_coupon(p,1.,0.,0.),36.)
        self.assertAlmostEqual(no_hit_oracle(p,1.),32.,delta=1e-12)
        self.assertAlmostEqual(fixed_coupon(p,1.,0.,0.),32.,delta=1e-12)

    def test_subunity_alias_worst_with_coupon_maturity(self):
        p=Inputs(30.,8.,1e-16)
        tau=.7
        self.assertNotEqual(math.exp(-p.q*tau),1.)
        self.assertGreater(abs(parent_coupon(p,tau,0.,0.)-no_hit_oracle(p,tau)),5.)
        self.assertAlmostEqual(fixed_coupon(p,tau,0.,0.),no_hit_oracle(p,tau),delta=2e-13)

    def test_tiny_q_no_hit_always_stable(self):
        for q in (math.nextafter(0.,1.),1e-300,1e-20,1e-17,1e-16,1e-14,1e-12,1e-10):
            for tau in (.25,.7,1.,1.3,2.):
                p=Inputs(30.,8.,q)
                actual=fixed_coupon(p,tau,0.,0.)
                oracle=no_hit_oracle(p,tau)
                self.assertAlmostEqual(actual,oracle,delta=max(2e-12,2e-12*abs(oracle)))

    def test_reject_nonzero_first_hit_at_small_positive_discount_product(self):
        for q in (math.nextafter(0.,1.),1e-20,1e-16,1e-12):
            p=Inputs(30.,2.,q)
            for F,G in ((.5,.5),(.5,.49999999999999994),(1e-30,1e-30)):
                with self.assertRaisesRegex(ArithmeticError,'stopped coupon'):
                    fixed_coupon(p,1.,F,G)

    def test_normal_regime_legacy_bit_equal(self):
        for q in (.001,.05,.4):
            p=Inputs(30.,2.,q,recovery=.3)
            for tau in (.25,1.,2.):
                for F,G in ((0.,0.),(.01,.007),(.4,.3),(.9,.2)):
                    self.assertEqual(fixed_coupon(p,tau,F,G),parent_coupon(p,tau,F,G))

    def test_zero_coupon_retains_legacy(self):
        for q in (1e-16,1e-12,.01):
            p=Inputs(30.,0.,q,recovery=.3)
            self.assertEqual(fixed_coupon(p,.7,.4,.3),parent_coupon(p,.7,.4,.3))

    def test_seeded_f64_no_hit_stress(self):
        rng=random.Random(202610301047)
        for _ in range(1500):
            q=10.**rng.uniform(-20.,-8.)
            tau=10.**rng.uniform(-1.,.7)
            c=10.**rng.uniform(-2.,1.)
            p=Inputs(30.,c,q)
            if q*tau<2.**-26:
                v=fixed_coupon(p,tau,0.,0.)
                want=no_hit_oracle(p,tau)
                self.assertAlmostEqual(v,want,delta=5e-12)

if __name__=='__main__': unittest.main()
