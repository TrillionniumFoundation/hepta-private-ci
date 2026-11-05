"""Numerical contracts for HX kernels; all comparisons have independent oracles."""

from dataclasses import replace
import math
import unittest

import numpy as np
from scipy.integrate import quad
from scipy.special import ndtr

from qualification.hcsn.reference import (
    HXParams, discounted_boundary_claim, discounted_first_passage, evaluate,
    first_passage_cdf, first_passage_density, first_passage_survival, hx_boundary,
    hx_debt, hx_equity, hx_equity_closed, normal_tail_integral, parameter_feasibility,
)


def derivative(function, x, step=1e-4):
    return (function(x-2*step)-8*function(x-step)+8*function(x+step)
            -function(x+2*step))/(12*step)


def second_derivative(function, x, step=3e-4):
    return (-function(x+2*step)+16*function(x+step)-30*function(x)
            +16*function(x-step)-function(x-2*step))/(12*step*step)


class FirstPassageTests(unittest.TestCase):
    def test_cdf_and_discounted_cdf_against_density_integrals(self):
        for mu in (-0.1, 0.0, 0.1):
            for x in (0.02, 0.2, 0.9):
                for horizon in (0.1, 1.0, 5.0):
                    with self.subTest(mu=mu, x=x, horizon=horizon):
                        pdf = lambda t: first_passage_density(t,x,mu,0.3)
                        self.assertAlmostEqual(first_passage_cdf(x,horizon,mu,0.3),
                                               quad(pdf,0,horizon,epsabs=1e-11)[0],places=10)
                        self.assertAlmostEqual(discounted_first_passage(x,horizon,mu,0.3,0.07),
                                               quad(lambda t:math.exp(-0.07*t)*pdf(t),
                                                    0,horizon,epsabs=1e-11)[0],places=10)

    def test_density_is_time_derivative(self):
        for mu in (-0.2, 0, 0.2):
            for horizon in (0.05, 0.5, 3):
                actual=first_passage_density(horizon,0.1,mu,0.2)
                numerical=derivative(lambda t:first_passage_cdf(0.1,t,mu,0.2),horizon,1e-5)
                self.assertAlmostEqual(actual,numerical,places=8)

    def test_laplace_and_eventual_default_limits(self):
        for mu in (-0.1, 0, 0.1):
            expected=1.0 if mu <= 0 else math.exp(-2*mu*0.2/0.3**2)
            self.assertAlmostEqual(discounted_boundary_claim(0.2,mu,0.3,0),expected)
            laplace=quad(lambda t:math.exp(-0.08*t)*first_passage_density(t,0.2,mu,0.3),
                         0,np.inf,epsabs=1e-11)[0]
            self.assertAlmostEqual(discounted_boundary_claim(0.2,mu,0.3,0.08),laplace,places=10)

    def test_time_zero_and_boundary_atom(self):
        self.assertEqual(first_passage_cdf(0,0,0,0.2),1)
        self.assertEqual(discounted_first_passage(0,0,0,0.2,0.05),1)
        self.assertEqual(first_passage_density(0,0,0,0.2),0)
        self.assertEqual(first_passage_density(1,0,0,0.2),0)
        self.assertEqual(first_passage_cdf(1,0,0,0.2),0)
        self.assertEqual(discounted_first_passage(1,0,0,0.2,0.05),0)
        self.assertEqual(first_passage_density(0,1,0,0.2),0)
        p=HXParams(); b=hx_boundary(p)
        self.assertEqual(hx_debt(0,0,p),p.recovery*b/p.maturity)
        self.assertEqual(hx_debt(0.1,0,p),p.p)
        result=evaluate(b,p,0)
        self.assertEqual((result['E'],result['F'],result['G'],result['f'],result['first_passage_atom']),
                         (0,1,1,0,1))

    def test_survival_and_deep_tails(self):
        for x in (1e-8, 1e-5, 0.1, 10):
            for mu in (-1, 0, 1):
                f=first_passage_cdf(x,0.3,mu,0.1)
                s=first_passage_survival(x,0.3,mu,0.1)
                self.assertTrue(0 <= f <= 1+1e-12)
                self.assertGreaterEqual(s,0)
                self.assertAlmostEqual(f+s,1,places=11)
        self.assertGreater(first_passage_survival(1e-8,1,0,0.2),0)
        self.assertTrue(np.isfinite(first_passage_cdf(10,0.01,-10,0.01)))

    def test_broadcasting(self):
        x=np.array([[0.01],[0.5]])
        times=np.array([0,0.2,1])
        got=first_passage_cdf(x,times,0,0.2)
        self.assertEqual(got.shape,(2,3))
        expected=np.array([[first_passage_cdf(xx,t,0,0.2) for t in times] for xx in x[:,0]])
        np.testing.assert_allclose(got,expected,rtol=0,atol=0)


class HXReferenceTests(unittest.TestCase):
    def test_divided_difference_against_positive_integral(self):
        for lam in (-3,-1e-8,0,1e-8,2):
            for u in (-4,-0.2,3):
                with self.subTest(lam=lam,u=u):
                    expected=quad(lambda y:math.exp(-lam*y)*ndtr(u*0.3-y/0.3),
                                  0,8,epsabs=1e-13,epsrel=1e-12)[0]
                    self.assertAlmostEqual(normal_tail_integral(lam,u,0.3),expected,places=11)
        for w in (-10,-3,0,3):
            expected=quad(lambda y:ndtr(w-y),0,30,epsabs=1e-14)[0]
            self.assertAlmostEqual(normal_tail_integral(0,w,1),expected,places=12)

    def test_original_regular_reference_values(self):
        # Reproduces the preexisting independently checked published-A7 scalar reference.
        p=HXParams()
        self.assertAlmostEqual(hx_boundary(p),121.48629220149449,places=10)
        self.assertAlmostEqual(hx_equity(0.1,p),6.077151191926724,places=10)
        self.assertAlmostEqual(hx_equity_closed(0.1,p),6.077151191926724,places=10)

    def test_formal_ode_solution_is_not_automatically_economic_equity(self):
        invalid=HXParams(sigma=0.2,maturity=0.05,ell=0.3)
        report=parameter_feasibility(invalid)
        self.assertFalse(report["local_admissible"])
        self.assertTrue(report["uncapped_recovery_exceeds_face"])
        self.assertGreater(report["boundary_running_cashflow"],0)
        self.assertLess(hx_equity(0.01,invalid),0)
        self.assertAlmostEqual(hx_equity_closed(0.01,invalid),hx_equity(0.01,invalid),places=8)
        valid=parameter_feasibility(HXParams())
        self.assertTrue(valid["local_admissible"])
        self.assertTrue(valid["sufficient_monotone_subdomain"])
        self.assertFalse(valid["uncapped_recovery_exceeds_face"])

    def test_zero_liquidity_and_zero_log_drift(self):
        for p in (HXParams(ell=0),HXParams(delta=0.03,ell=0)):
            b=hx_boundary(p)
            self.assertGreater(b,0)
            for x in (0,0.01,0.1,0.5):
                self.assertAlmostEqual(hx_equity_closed(x,p),hx_equity(x,p),places=9)
                self.assertTrue(np.isfinite(hx_debt(x,1,p)))
            for ell in (1e-4,1e-6,1e-8,1e-10):
                near=replace(p,ell=ell)
                self.assertLess(abs(hx_boundary(near)-b),500*ell+1e-10)
        p=HXParams(ell=0)
        # Finite, continuous one-sided liquidity sensitivity; no epsilon substitution.
        slopes=[(hx_boundary(replace(p,ell=h))-hx_boundary(p))/h for h in (1e-5,1e-6,1e-7)]
        self.assertLess(max(slopes)-min(slopes),0.02)

    def test_boundary_condition_from_independent_integral(self):
        for p in (HXParams(),HXParams(ell=0),HXParams(delta=0.03,ell=0.2),HXParams(maturity=5)):
            b=hx_boundary(p); eta=p.roots()[3]
            integral=p.delta*b/(eta-1)+quad(lambda x:math.exp(-eta*x)*(
                -(1-p.tax)*p.coupon+hx_debt(x,p.maturity,p,b)-p.p),
                0,np.inf,epsabs=1e-10,epsrel=1e-11)[0]
            self.assertLess(abs(integral),2e-8)
            self.assertEqual(hx_equity(0,p),0)
            # Genuine right derivative from values, not a clamped exterior extension.
            h=1e-6
            slope=(-3*hx_equity(0,p)+4*hx_equity(h,p)-hx_equity(2*h,p))/(2*h)
            self.assertLess(abs(slope),1e-7)

    def test_debt_pde_and_payoff(self):
        for p in (HXParams(),HXParams(ell=0),HXParams(delta=0.03)):
            for x in (0.05,0.3,1):
                for horizon in (0.15,0.8):
                    f=lambda y:hx_debt(y,horizon,p)
                    dt=derivative(lambda t:hx_debt(x,t,p),horizon,1e-5)
                    residual=dt-p.mu*derivative(f,x)-p.sigma**2/2*second_derivative(f,x)-p.c+p.q*f(x)
                    self.assertLess(abs(residual),3e-5)
            b=hx_boundary(p)
            self.assertAlmostEqual(hx_debt(0,0.3,p),p.recovery*b/p.maturity,places=11)

    def test_equity_ode_and_closed_form_against_oracle(self):
        for p in (HXParams(),HXParams(ell=0),HXParams(delta=0.03),HXParams(recovery=0)):
            b=hx_boundary(p)
            for x in (0.04,0.1,0.5,1):
                f=lambda y:hx_equity(y,p)
                cashflow=p.delta*b*math.exp(x)-(1-p.tax)*p.coupon+hx_debt(x,p.maturity,p)-p.p
                residual=p.r*f(x)-p.mu*derivative(f,x)-p.sigma**2/2*second_derivative(f,x)-cashflow
                self.assertLess(abs(residual),3e-5)
                self.assertAlmostEqual(hx_equity_closed(x,p),f(x),places=8)

    def test_small_distance_and_parameter_limits(self):
        for p in (HXParams(ell=0),HXParams(maturity=0.01),HXParams(maturity=30),
                  HXParams(delta=1e-8),HXParams(sigma=0.03),HXParams(recovery=1)):
            b=hx_boundary(p)
            self.assertTrue(math.isfinite(b) and b>0)
            g0=p.delta*b-(1-p.tax)*p.coupon+p.recovery*b/p.maturity-p.p
            expected=-g0/p.sigma**2
            self.assertAlmostEqual(hx_equity(1e-7,p)/(1e-7**2)/expected,1,places=4)
            self.assertTrue(math.isfinite(hx_equity(0.1,p)))
            self.assertGreaterEqual(hx_equity(0.1,p),-1e-9)

    def test_money_scale_homogeneity(self):
        p=HXParams(); b=hx_boundary(p)
        for scale in (0.001,10,1e3):
            scaled=replace(p,coupon=p.coupon*scale,principal=p.principal*scale)
            self.assertAlmostEqual(hx_boundary(scaled)/(scale*b),1,places=12)
            self.assertAlmostEqual(hx_equity(.2,scaled)/(scale*hx_equity(.2,p)),1,places=11)
            self.assertAlmostEqual(hx_debt(.2,.5,scaled)/(scale*hx_debt(.2,.5,p)),1,places=12)
            result=evaluate(b*math.exp(.2),p,.5)
            scaled_result=evaluate(b*scale*math.exp(.2),scaled,.5)
            for key in ('F','G','f'):
                self.assertAlmostEqual(result[key],scaled_result[key],places=12)

    def test_full_hx_time_unit_covariance(self):
        # C is an annual total coupon; c=C/m is a coupon density. The debt
        # unit is tied to the maturity ladder, so d scales as inverse time.
        p=HXParams(); b=hx_boundary(p); value=b*math.exp(0.2)
        original=evaluate(value,p,0.7)
        original_debt=hx_debt(0.2,0.7,p)
        for scale in (0.01,0.1,10,100):
            transformed=replace(p,r=p.r/scale,delta=p.delta/scale,ell=p.ell/scale,
                                coupon=p.coupon/scale,sigma=p.sigma/math.sqrt(scale),
                                maturity=p.maturity*scale)
            actual=evaluate(value,transformed,0.7*scale)
            for key in ('b','E','F','G'):
                self.assertAlmostEqual(actual[key]/original[key],1,places=11)
            self.assertAlmostEqual(actual['f']*scale/original['f'],1,places=11)
            self.assertAlmostEqual(hx_debt(0.2,0.7*scale,transformed)*scale/original_debt,1,places=11)

    def test_parameter_domains_are_not_silently_clamped(self):
        for changes in ({'sigma':0},{'r':0},{'delta':0},{'maturity':0},{'ell':-0.1},
                        {'recovery':1.1},{'tax':1},{'coupon':-1},{'principal':0}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                replace(HXParams(),**changes)
        with self.assertRaises(ValueError):
            first_passage_cdf(-0.1,1,0,0.2)
        with self.assertRaises(ValueError):
            evaluate(hx_boundary(HXParams())*0.9,HXParams(),1)


if __name__=='__main__':
    unittest.main()
