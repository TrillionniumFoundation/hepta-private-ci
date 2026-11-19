"""Independent mathematical, numerical and refusal tests for HX spatial tail."""
from fractions import Fraction
from types import SimpleNamespace
from decimal import Decimal
import math
import unittest

from .hx_certified_brownian_tail import (
    _doob_probability, ceil_decimal_string, floor_decimal_string,
    certified_hx_bond_spatial_tail, UnresolvedTailCertificate)


def _financial(**patch):
    args=dict(rate=.05,payout=.03,volatility=.25,maturity=2.,
              principal=60.,coupon=4.,tax_shield=.25,recovery=.6,
              shock_intensity=1.,sale_fraction=.015)
    args.update(patch)
    return SimpleNamespace(**args)


def _reflection_probability(mu,sigma,distance,T):
    # Independent reflection-law formula via the standard library erfc.
    from scipy.special import log_ndtr,ndtr
    s=sigma*math.sqrt(T)
    a=(mu*T-distance)/s
    v=(-mu*T-distance)/s
    second=math.exp(2*mu*distance/sigma**2+float(log_ndtr(v)))
    return float(ndtr(a))+second


class TailCertificateTests(unittest.TestCase):
    def test_martingale_envelope_strictly_dominates_reflection(self):
        for mu in (-.5,-.1,0.,.1,.5):
            for sigma in (.2,.6,1.2):
                for distance in (.2,1.,3.):
                    for T in (.3,1.5):
                        cap,x=_doob_probability(drift=Fraction(mu),
                              diffusion=Fraction(sigma),
                              duration=Fraction(T),distance=Fraction(distance))
                        analytic=_reflection_probability(mu,sigma,distance,T)
                        self.assertGreaterEqual(float(cap)+2e-15,analytic)
                        self.assertLessEqual(cap,1)
                        self.assertGreaterEqual(x,0)

    def test_exact_decimal_ceil(self):
        values=(Fraction(1,3),Fraction(1,10**100),
                Fraction(22,7),Fraction(1,9),Fraction(103,1000))
        for v in values:
            out=ceil_decimal_string(v)
            self.assertGreaterEqual(Fraction(Decimal(out)),v)
        self.assertEqual(ceil_decimal_string(Fraction(0)),'0')
        self.assertEqual(ceil_decimal_string(Fraction(1,10**80)),'1e-45')
        for v in values:
            self.assertLessEqual(Fraction(Decimal(floor_decimal_string(v))),v)

    def test_financial_spatial_tail_and_nonadmission(self):
        for sale in (0.,.015,.2):
            p=_financial(sale_fraction=sale)
            proof=certified_hx_bond_spatial_tail(p,101.324,
                            log_upper=3.6, log_state=.2)
            self.assertLessEqual(Decimal(proof.local_debt_spatial_error_bound),
                                 Decimal(proof.uniform_debt_spatial_error_bound))
            self.assertFalse(proof.scientific_gate_closed)
            self.assertFalse(proof.production_activation)
            self.assertFalse(proof.debt_error_budget_complete)
            with self.assertRaises(UnresolvedTailCertificate):
                proof.to_total_pde_error_budget()

    def test_stronger_upper_domain_reduces_uniform_bound(self):
        p=_financial()
        small=certified_hx_bond_spatial_tail(p,70.,log_upper=2.)
        large=certified_hx_bond_spatial_tail(p,70.,log_upper=4.)
        self.assertLess(Decimal(large.uniform_debt_spatial_error_bound),
                        Decimal(small.uniform_debt_spatial_error_bound))

    def test_stress_negative_drift_and_zero_recovery_difference(self):
        p=_financial(payout=.19,recovery=1.)
        v=certified_hx_bond_spatial_tail(p,80.,log_upper=3.,duration=.4,
                                          log_state=1.)
        self.assertTrue(Decimal(v.uniform_debt_spatial_error_bound)>=0)
        # C exactly zero when par=base=recovery, so bound exactly 0.
        p=_financial(coupon=3.,principal=6.,recovery=.125,
                     shock_intensity=0.,rate=.5,maturity=2.)
        # c/T/q = 1.5/.5=3, P/T=3, recovery*b/T=3 when b=48.
        p.recovery=.125
        zero=certified_hx_bond_spatial_tail(p,48.,log_upper=1.)
        self.assertEqual(zero.uniform_debt_spatial_error_bound,'0')

    def test_resource_limit_fail_closed(self):
        with self.assertRaises(UnresolvedTailCertificate):
            certified_hx_bond_spatial_tail(_financial(volatility=1e-290),
                                           60.,log_upper=3.)

    def test_invalid_physical_domain_refused(self):
        for kw in ({'sale_fraction':-1.},{'maturity':0.},
                   {'volatility':float('nan')},{'recovery':2.}):
            with self.subTest(kw=kw),self.assertRaises(UnresolvedTailCertificate):
                certified_hx_bond_spatial_tail(_financial(**kw),60.,log_upper=2.)
        for b,L,y,T in ((0.,3.,0.,1.),(60.,0.,0.,1.),
                        (60.,3.,3.,1.),(60.,3.,0.,3.),
                        (60.,13.,0.,1.)):
            with self.subTest(b=b,L=L,y=y,T=T),self.assertRaises(UnresolvedTailCertificate):
                certified_hx_bond_spatial_tail(_financial(),b,
                         log_upper=L,log_state=y,duration=T)
        with self.assertRaises(UnresolvedTailCertificate):
            certified_hx_bond_spatial_tail(_financial(),60.,log_upper=3.,taylor_terms=2)

if __name__=='__main__':
    unittest.main()
