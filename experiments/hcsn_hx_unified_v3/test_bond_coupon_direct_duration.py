"""Research-only density-weighted coupon duration without subtracting F-G.

Frozen 100-dps references integrate the Brownian hitting-time density
x/(sigma sqrt(2*pi*t**3))*exp(-(x+drift*t)**2/(2*sigma**2*t))
against (1-exp(-q*t))/q over [0,h], with independently evaluated F.
The references are NOT rigorous interval enclosures, and the opt-in output
MUST NOT authorize production activation.
"""
import math
import unittest

from .bond_fpt_independent import independent_bond, integrate_passage


class DirectCouponDurationTests(unittest.TestCase):
    _REFS = (
        # (x, drift, sigma, q, h, independent 100-dps coupon PV)
        (.7,.01,.22,1e-20,3.,2.9521915621419764244500489684124375039155),
        (.005,-.03,.2,1e-20,2.,.0489023102661864542344262459387713764975),
        (.1,-.5,.3,1e-20,3.,.1997870875140707993475158183502363453239),
        (7.574364447822511,-.10335391582430709,.5722860259650109,
         2.2140977267535007e-16,3.394435816586972,
         3.3944358165861241828787692424615186270615),
        (.7,.01,.22,.09,3.,2.5905664092795212411543778650035381551373),
    )

    def test_opt_in_density_duration_matches_independent_100dps(self):
        for x,drift,sigma,discount,horizon,reference in self._REFS:
            with self.subTest(x=x,discount=discount):
                bond,p=independent_bond(
                    x=x,drift=drift,sigma=sigma,discount=discount,
                    horizon=horizon,coupon_per_bond=1.,
                    principal_per_bond=0.,recovery_per_bond=0.,
                    direct_coupon_duration=True)
                self.assertLess(abs(bond-reference),2e-12)
                self.assertIsNotNone(p.default_coupon_duration)
                self.assertGreaterEqual(p.default_coupon_duration,0.)
                self.assertGreaterEqual(p.duration_error_estimate,0.)
                full=-math.expm1(-discount*horizon)/discount
                self.assertLessEqual(bond,full)

    def test_default_keeps_historical_refusals(self):
        for x,drift,sigma,discount,horizon,_ in self._REFS[:4]:
            with self.subTest(x=x,discount=discount):
                with self.assertRaises(ArithmeticError):
                    independent_bond(x=x,drift=drift,sigma=sigma,
                        discount=discount,horizon=horizon,
                        coupon_per_bond=1.,principal_per_bond=0.,
                        recovery_per_bond=0.)

    def test_default_passage_api_has_no_opt_in_duration(self):
        p=integrate_passage(.7,drift=.01,sigma=.22,discount=.09,horizon=3.)
        self.assertIsNone(p.default_coupon_duration)
        self.assertIsNone(p.duration_error_estimate)

    def test_zero_coupon_does_not_evaluate_optional_duration(self):
        # Optional integral must not change a principal-only bond's domain.
        q=math.ldexp(1.,-1074)
        original,_=independent_bond(x=50.,drift=.2,sigma=.2,
            discount=q,horizon=.25,coupon_per_bond=0.,
            principal_per_bond=1.,recovery_per_bond=0.)
        direct,p=independent_bond(x=50.,drift=.2,sigma=.2,
            discount=q,horizon=.25,coupon_per_bond=0.,
            principal_per_bond=1.,recovery_per_bond=0.,
            direct_coupon_duration=True)
        self.assertEqual(original,direct)
        self.assertIsNone(p.default_coupon_duration)

    def test_unresolved_peak_still_rejected_in_opt_in(self):
        with self.assertRaises(ArithmeticError):
            independent_bond(x=2.,drift=-.5,sigma=1e-30,
                discount=.1,horizon=10.,coupon_per_bond=1.,
                principal_per_bond=0.,recovery_per_bond=0.,
                direct_coupon_duration=True)


if __name__ == '__main__':
    unittest.main()
