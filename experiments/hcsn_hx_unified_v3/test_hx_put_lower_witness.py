"""Independent high precision and adversarial tests; no mock production input."""
import unittest
from dataclasses import dataclass, replace
from fractions import Fraction
import mpmath as mp
from .hx_put_lower_witness import (
    certify_fixed_barrier_put_hit_lower, certify_fixed_barrier_put_dual,
    UnresolvedPutLowerWitness,
    _positive_exp_bracket, _negative_exp_bracket, _log_lower_ge_one,
    _sqrt_bracket)

@dataclass(frozen=True)
class HX:
    rate:float=.05
    payout:float=.03
    volatility:float=.25
    maturity:float=2.
    principal:float=60.
    coupon:float=4.
    tax_shield:float=.25
    recovery:float=.6
    shock_intensity:float=1.
    sale_fraction:float=.015


def mf(f):
    if isinstance(f,str):
        return mp.mpf(f)
    if not isinstance(f,Fraction):
        f=Fraction.from_float(float(f))
    return mp.mpf(f.numerator)/f.denominator

class PutDualTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        mp.mp.dps=120

    def test_transcendental_enclosures(self):
        for x in (Fraction(1,1000),Fraction(1,2),Fraction(8),Fraction(100)):
            if x<=8:
                lo,hi=_positive_exp_bracket(x)
                self.assertLessEqual(mf(lo),mp.exp(mf(x)))
                self.assertGreaterEqual(mf(hi),mp.exp(mf(x)))
            lo,hi=_negative_exp_bracket(x)
            self.assertLessEqual(mf(lo),mp.exp(-mf(x)))
            self.assertGreaterEqual(mf(hi),mp.exp(-mf(x)))
        for x in (Fraction(1),Fraction(1001,1000),Fraction(3,2),Fraction(3),Fraction(8)):
            self.assertLessEqual(mf(_log_lower_ge_one(x)),mp.log(mf(x)))
        for x in (Fraction(1,10**8),Fraction(2,3),Fraction(1),Fraction(10**8)):
            lo,hi=_sqrt_bracket(x)
            self.assertLessEqual(mf(lo),mp.sqrt(mf(x)))
            self.assertGreaterEqual(mf(hi),mp.sqrt(mf(x)))

    def test_policy_lower_bound_below_exact_perpetual_put(self):
        cases=[(HX(),64.62517667527493),
               (HX(sale_fraction=.2),101.32402860907811),
               (HX(rate=.04,payout=.07,volatility=.32),90.0),
               (HX(rate=.07,payout=.025,volatility=.2),90.0),
               (HX(rate=.03,payout=.045,volatility=.21),90.0)]
        positive=0
        for p,b in cases:
            with self.subTest(p=p,b=b):
                cert=certify_fixed_barrier_put_hit_lower(p,candidate_barrier=b,log_upper=3.6)
                r,delta,sig,T=map(mf,(p.rate,p.payout,p.volatility,p.maturity))
                q=r+mf(p.shock_intensity)*mf(p.sale_fraction)
                c=mf(p.coupon)/T
                par=mf(p.principal)/T
                C=(1-mf(p.tax_shield))*mf(p.coupon)+par
                K=max(mp.mpf(0),(C-(c/q+mp.exp(-q*T)*(par-c/q)))/r)
                gamma=(r-delta-sig**2/2+mp.sqrt((r-delta-sig**2/2)**2+2*r*sig**2))/sig**2
                bb=mf(b)
                A=bb*mp.exp(mf(3.6))
                self.assertLessEqual(mf(cert.gamma_lower),gamma)
                self.assertGreaterEqual(mf(cert.gamma_upper),gamma)
                self.assertLessEqual(mf(cert.strike_lower),K)
                self.assertFalse(cert.production_activation)
                with self.assertRaises(UnresolvedPutLowerWitness):
                    cert.certify_p0()
                if cert.exercise_is_strictly_above_barrier:
                    z=mf(Fraction(cert.exact_rational_hit_level))
                    self.assertGreater(z,bb)
                    self.assertLessEqual(z,A)
                    exact_hit=max(mp.mpf(0),K-z)*mp.exp(-gamma*mp.log(A/z))
                    self.assertLessEqual(mf(cert.put_lower),exact_hit)
                    zstar=max(bb,min(A,gamma*K/(gamma+1)))
                    exact_envelope=max(mp.mpf(0),K-zstar)*mp.exp(-gamma*mp.log(A/zstar))
                    self.assertLessEqual(mf(cert.put_lower),exact_envelope)
                    positive+=1
                else:
                    self.assertEqual(cert.put_lower,'0.000000000000')
        self.assertGreaterEqual(positive,1)

    def test_120_multiparameter_feasible_hits_against_independent_mpmath(self):
        checked=positive=0
        for r in (.03,.05,.09):
            for delta in (.015,.06):
                for volatility in (.15,.35):
                    for barrier in (30.,55.,80.,105.,130.):
                        for L in (.7,3.6):
                            p=HX(rate=r,payout=delta,volatility=volatility,
                                 sale_fraction=.2)
                            cert=certify_fixed_barrier_put_hit_lower(p,
                                candidate_barrier=barrier,log_upper=L)
                            rr,dd,ss,tt=map(mf,(r,delta,volatility,p.maturity))
                            q=rr+mf(p.shock_intensity)*mf(p.sale_fraction)
                            c=mf(p.coupon)/tt;par=mf(p.principal)/tt
                            C=(1-mf(p.tax_shield))*mf(p.coupon)+par
                            K=max(mp.mpf(0),(C-(c/q+mp.exp(-q*tt)*(par-c/q)))/rr)
                            gamma=(rr-dd-ss**2/2+
                                   mp.sqrt((rr-dd-ss**2/2)**2+2*rr*ss**2))/ss**2
                            self.assertLessEqual(mf(cert.strike_lower),K)
                            self.assertLessEqual(mf(cert.gamma_lower),gamma)
                            self.assertGreaterEqual(mf(cert.gamma_upper),gamma)
                            if cert.exercise_is_strictly_above_barrier:
                                z=mf(Fraction(cert.exact_rational_hit_level))
                                self.assertGreater(z,mf(barrier))
                                self.assertLessEqual(z,mf(barrier)*mp.exp(mf(L)))
                                payoff=(K-z)*mp.exp(-gamma*(mf(L)-mp.log(z/mf(barrier))))
                                self.assertGreaterEqual(payoff,0)
                                self.assertLessEqual(mf(cert.put_lower),payoff)
                                positive+=1
                            else:
                                self.assertEqual(cert.put_lower,'0.000000000000')
                            checked+=1
        self.assertEqual(checked,120)
        self.assertGreater(positive,0)

    def test_independent_dual_straddles_120_grid_analytic_optima(self):
        n=positive=0
        for r in (.03,.05,.09):
            for delta in (.015,.06):
                for volatility in (.15,.35):
                    for barrier in (30.,55.,80.,105.,130.):
                        for L in (.7,3.6):
                            p=HX(rate=r,payout=delta,volatility=volatility,
                                 sale_fraction=.2)
                            cert=certify_fixed_barrier_put_dual(p,
                                candidate_barrier=barrier,log_upper=L)
                            rr,dd,ss,tt=map(mf,(r,delta,volatility,p.maturity))
                            q=rr+mf(p.shock_intensity)*mf(p.sale_fraction)
                            c=mf(p.coupon)/tt;par=mf(p.principal)/tt
                            C=(1-mf(p.tax_shield))*mf(p.coupon)+par
                            K=max(mp.mpf(0),(C-(c/q+mp.exp(-q*tt)*(par-c/q)))/rr)
                            gamma=(rr-dd-ss**2/2+
                                   mp.sqrt((rr-dd-ss**2/2)**2+2*rr*ss**2))/ss**2
                            zstar=max(mf(barrier),gamma*K/(gamma+1))
                            # An analytic obstacle upper even when zstar>A0;
                            # this is exactly the maximization underlying the
                            # r-harmonic upper, not an attainable policy claim.
                            analytic=(max(mp.mpf(0),K-zstar)*
                                mp.exp(-gamma*mf(L))*(zstar/mf(barrier))**gamma)
                            self.assertLessEqual(mf(cert.put_lower),analytic)
                            self.assertGreaterEqual(mf(cert.put_upper),analytic)
                            self.assertLessEqual(mf(cert.strike_lower),K)
                            self.assertGreaterEqual(mf(cert.strike_upper),K)
                            self.assertFalse(cert.production_activation)
                            if cert.witness_level!='NONE':positive+=1
                            n+=1
        self.assertEqual(n,120)
        self.assertGreater(positive,0)

    def test_high_liquidity_known_parent_upper_is_sharpened_not_faked(self):
        p=HX(sale_fraction=.2)
        cert=certify_fixed_barrier_put_dual(p,
            candidate_barrier=101.32402860907811,log_upper=3.6)
        self.assertEqual(cert.put_lower,'2.619402148447')
        self.assertLessEqual(mf(cert.put_upper),mf('2.619570396928'))
        self.assertLess(mf(cert.put_upper)-mf(cert.put_lower),mf('0.000000001'))
        with self.assertRaises(UnresolvedPutLowerWitness):
            cert.certify_p0()

    def test_small_L_high_activity_and_bad_domains(self):
        p=HX(sale_fraction=.2);b=101.32402860907811
        for L in (0.001,0.05,0.5,1.2,3.6):
            c=certify_fixed_barrier_put_hit_lower(p,candidate_barrier=b,log_upper=L)
            self.assertFalse(c.scientific_gate_closed)
            if c.exercise_is_strictly_above_barrier:
                self.assertGreater(Fraction(c.exact_rational_hit_level),Fraction.from_float(b))
        for kw in [dict(candidate_barrier=-1,log_upper=3.6),
                   dict(candidate_barrier=b,log_upper=9),
                   dict(candidate_barrier=b,log_upper=0),
                   dict(candidate_barrier=b,log_upper=3.6,taylor_terms=8)]:
            with self.assertRaises(UnresolvedPutLowerWitness):
                certify_fixed_barrier_put_hit_lower(p,**kw)
        for bad in (replace(p,payout=0),replace(p,rate=-.1),replace(p,volatility=0)):
            with self.assertRaises(UnresolvedPutLowerWitness):
                certify_fixed_barrier_put_hit_lower(bad,candidate_barrier=b,log_upper=3.6)

if __name__=='__main__':
    unittest.main()
