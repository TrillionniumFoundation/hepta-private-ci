"""Independent reference audits for full financial HX and scalar stopping/QVI.

Run: python -m unittest -v test_oracles
No pretraining, benchmark superiority, GPU, or deployed owner is claimed.
"""

from dataclasses import replace
import math
import random
import unittest

import numpy as np
from scipy.integrate import quad
from scipy.optimize import brentq

from .hx import HX, boundary, bond_value, equity_closed, equity_resolvent
from .hx import mechanism_channels, default_probability, discounted_default_factor
from .stopping import Stop, one_shot_boundary, one_shot_value
from .stopping import regenerative_boundary, regenerative_boundary_independent
from .stopping import regenerative_value, qvi


def independent_boundary(p: HX) -> float:
    """Solve integrated HX smooth-fit condition, not formula (12)."""
    eta=p.eta
    const=(1-p.tax_shield)*p.coupon+p.per_bond_principal
    def residual(b):
        def f(y):
            return math.exp(-eta*y)*bond_value(p,b*math.exp(y),p.maturity,b)
        integral=quad(f,0,50,epsabs=3e-11,epsrel=2e-11,limit=250)[0]
        integral+=p.per_bond_coupon/p.q*math.exp(-eta*50)/eta
        return (.5*p.volatility**2*(p.gamma+1)*b-const/eta+integral)
    lo,hi=1e-8,10000.0
    assert residual(lo)<0 and residual(hi)>0, (p,residual(lo),residual(hi))
    return brentq(residual,lo,hi,xtol=5e-10,rtol=1e-11)


class HXTests(unittest.TestCase):
    def test_bond_default_and_maturity_boundaries(self):
        for p in (HX(), HX(sale_fraction=0),HX(payout=0)):
            b=boundary(p)
            self.assertAlmostEqual(bond_value(p,b,p.maturity,b),p.recovery*b/p.maturity)
            self.assertAlmostEqual(bond_value(p,1.5*b,0,b),p.per_bond_principal)
            for tau in (0,1e-8,p.maturity/2,p.maturity):
                for ratio in (1.00001,1.1,2,4):
                    asset=b*ratio
                    P=default_probability(p,asset,tau,b)
                    D=discounted_default_factor(p,asset,tau,b)
                    self.assertTrue(0<=D<=P+1e-12<=1+1e-10)
            self.assertLess(abs(bond_value(p,b*1.000000001,p.maturity,b)-p.recovery*b/p.maturity),1e-5)

    def test_closed_equity_vs_independent_feynman_kac(self):
        cases=[HX(),HX(payout=0),HX(sale_fraction=0),HX(sale_fraction=1e-9),
               HX(shock_intensity=0),HX(payout=1e-5),HX(sale_fraction=.2),
               HX(volatility=.4,maturity=5,rate=.09,payout=.07)]
        for p in cases:
            with self.subTest(p=p):
                b=boundary(p)
                for r in (1.0001,1.03,1.25,2.5,5):
                    a,b2=equity_closed(p,b*r,b),equity_resolvent(p,b*r,b)
                    self.assertLess(abs(a-b2),2e-7*(1+abs(a)))
                    # The smooth-pasting algebra is not a global nonnegative
                    # equity certificate: extreme liquidity can violate it.

    def test_extreme_liquidity_exposes_nonoptimal_smooth_fit(self):
        p=HX(sale_fraction=.2)
        b=boundary(p)
        near=equity_closed(p,b*1.01,b)
        self.assertLess(near,0)
        # Negative value is preserved as an invalid obstacle witness, never
        # clipped to zero or recorded as a successful optimal stopping case.
        self.assertLess(abs(near-equity_resolvent(p,b*1.01,b)),1e-7)

    def test_independent_smooth_fit_root_and_gradient(self):
        cases=[HX(),HX(sale_fraction=0),HX(payout=0),HX(shock_intensity=0),
               HX(rate=.11,payout=.05,volatility=.35,maturity=1.2)]
        for p in cases:
            with self.subTest(p=p):
                b=boundary(p)
                self.assertLess(abs(b-independent_boundary(p))/b,1e-8)
                h=1e-4*b
                self.assertLess(abs((equity_closed(p,b+h,b)-equity_closed(p,b,b))/h),.002)
                self.assertGreaterEqual(equity_closed(p,b+10*h,b),0)

    def test_equity_ode_with_independent_second_difference(self):
        for p in (HX(), HX(payout=0), HX(sale_fraction=0), HX(maturity=.5)):
            b=boundary(p)
            dx=.001
            for x in (.1,.3,.7,1.2):
                e=lambda t:equity_closed(p,b*math.exp(t),b)
                y=e(x)
                deriv=(e(x-2*dx)-8*e(x-dx)+8*e(x+dx)-e(x+2*dx))/(12*dx)
                second=(-e(x-2*dx)+16*e(x-dx)-30*y+16*e(x+dx)-e(x+2*dx))/(12*dx*dx)
                f=p.payout*b*math.exp(x)-(1-p.tax_shield)*p.coupon+bond_value(p,b*math.exp(x),p.maturity,b)-p.per_bond_principal
                error=p.rate*y-(p.rate-p.payout-.5*p.volatility**2)*deriv-.5*p.volatility**2*second-f
                self.assertLess(abs(error),2e-5*(1+abs(y)),(p,x,error))

    def test_zero_liquidity_limit_and_quantized_inputs(self):
        p=HX()
        for q in (.03,.0):
            template=replace(p,payout=q,sale_fraction=0)
            b0=boundary(template)
            b1=boundary(replace(template,sale_fraction=1e-8))
            self.assertLess(abs(b1-b0)/b0,2e-6)
            self.assertLess(abs(equity_closed(template,b0*2,b0)-equity_closed(replace(template,sale_fraction=1e-8),b1*2,b1)),3e-4)
        # This is explicitly INPUT quantization to fp32, not a fp32 kernel test.
        for ratio in (1.1,1.7,4):
            base=boundary(p)
            low=HX(**{k:float(np.float32(v)) for k,v in vars(p).items()})
            b2=boundary(low)
            a=equity_closed(p,base*ratio,base)
            c=equity_closed(low,b2*ratio,b2)
            self.assertLess(abs(a-c)/(1+abs(a)),1e-4)

    def test_channel_accounting(self):
        p=HX()
        b=boundary(p)
        out=mechanism_channels(p,b*1.6,b)
        self.assertAlmostEqual(out.rollover_margin,bond_value(p,b*1.6,p.maturity,b)-p.per_bond_principal)
        self.assertGreater(out.default_probability,out.discounted_default_factor)
        self.assertGreater(out.equity,0)

    def test_invalid_domain_rejected(self):
        p=HX()
        for change in ({'rate':0},{'volatility':-1},{'maturity':0},
                       {'principal':0},{'shock_intensity':-1},
                       {'recovery':1.1},{'sale_fraction':1.1},
                       {'tax_shield':-1},{'coupon':math.nan},
                       {'payout':math.inf}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                replace(p,**change)
        with self.assertRaises(ValueError):
            bond_value(p,-1,1)
        with self.assertRaises(ValueError):
            bond_value(p,50,math.inf)

    def test_seeded_parameter_stress(self):
        rng=random.Random(20261030)
        accepted=0
        for _ in range(48):
            p=HX(rate=rng.uniform(.015,.14),payout=rng.uniform(0,.09),
                 volatility=rng.uniform(.12,.6),maturity=rng.uniform(.5,7),
                 principal=rng.uniform(20,100),coupon=rng.uniform(1,13),
                 tax_shield=rng.uniform(.0,.6),recovery=rng.uniform(.1,.95),
                 shock_intensity=rng.uniform(0,5),sale_fraction=rng.choice((0.0,1e-9,rng.uniform(.001,.1))))
            try:
                b=boundary(p)
            except ValueError as e:
                # A nonpositive boundary is a documented admissible edge:
                # no finite positive default threshold is not a valid solution.
                self.assertIn('No finite positive HX',str(e))
                continue
            v=b*1.6
            error=abs(equity_closed(p,v,b)-equity_resolvent(p,v,b))
            self.assertLess(error/(1+abs(v)),3e-8,(p,error))
            accepted+=1
        self.assertGreaterEqual(accepted,30)


class StopTests(unittest.TestCase):
    cases=(Stop(.1,.4,.1,1,0,.3),Stop(-.3,1,.01,.4,-1,1),
           Stop(.5,.05,1,1,0,0),Stop(0,.6,.5,1,0,2))

    def test_one_shot_optimum(self):
        for p in self.cases:
            b=one_shot_boundary(p)
            self.assertGreater(b,p.cost)
            x=p.reset
            v=one_shot_value(p,x)
            for shift in (-.5,-.1,.1,.5):
                rival=max(x,p.cost+1e-6,b+shift)
                val=(rival-p.cost)*math.exp(-p.kappa*(rival-x))
                self.assertLessEqual(val,v+1e-9)

    def test_renewal_boundary_root_and_qvi(self):
        for p in self.cases:
            b=regenerative_boundary(p)
            self.assertLess(abs(b-regenerative_boundary_independent(p)),1e-10)
            self.assertLessEqual(b,one_shot_boundary(p)+1e-10)
            for shift in (-.8,-.2,.2,.8):
                rival=max(p.cost+1e-6,p.reset+1e-6,b+shift)
                val=regenerative_value(p,p.reset,boundary=rival)
                self.assertLessEqual(val,regenerative_value(p,p.reset,boundary=b)+1e-9)
            for x in (p.reset,b-.5,b-.1,b-1e-5,b,b+.1,b+.5):
                r=qvi(p,x)
                self.assertLessEqual(r['obstacle'],1e-9)
                self.assertLessEqual(r['generator'],1e-9)
                self.assertLess(abs(r['complementarity']),1e-9)

    def test_no_refractory_limit(self):
        p=self.cases[0]
        a=replace(p,refractory=0)
        b=replace(p,refractory=1e-8)
        self.assertLess(abs(regenerative_boundary(a)-regenerative_boundary(b)),1e-6)
        self.assertGreater(regenerative_boundary(replace(p,refractory=100)),regenerative_boundary(p))

    def test_rejects_noncontractive_domain(self):
        p=self.cases[0]
        with self.assertRaises(ValueError):
            replace(p,reset=p.cost)
        with self.assertRaises(ValueError):
            replace(p,diffusion=0)
        with self.assertRaises(ValueError):
            replace(p,discount=0)
        with self.assertRaises(ValueError):
            replace(p,refractory=-.5)


if __name__=='__main__':
    unittest.main()
