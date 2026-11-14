import math
from dataclasses import replace
import unittest
from mpmath import mp
from fpt_reference import FPT,formula
from fpt_positive_gap import positive_gap,compare_gap,truncated_hit_first_moment
from simplified_stopping import SimpleStopping,evaluate,derivative_check

class TestIndependentPositiveRiskGap(unittest.TestCase):
    def test_near_barrier_gap_not_lost_to_f64(self):
        sigma=1.8581469732429565
        rate=.007595780582070804
        p=FPT(math.log(1.000000000000002),rate-3.5072936797757205e-7-sigma**2/2,
              sigma,2.2216211523554883e-08,rate)
        comparison=compare_gap(p,85)
        with mp.workdps(85):
            a=mp.mpf(comparison['positive_gap'])
            b=mp.mpf(comparison['subtracted_high_precision_gap'])
            self.assertGreater(a,0)
            self.assertLess(abs(a-b)/a,mp.mpf('1e-65'))

    def test_many_sign_and_crosschecks(self):
        for mu in [-.4,0,.4]:
            for discount in [0,.001,.7]:
                with self.subTest(mu=mu,discount=discount):
                    p=FPT(.8,mu,.65,1.2,discount)
                    d=positive_gap(p,65)
                    with mp.workdps(70):
                        self.assertGreaterEqual(mp.mpf(d['gap']),0)
                    if discount:
                        chk=compare_gap(p,65)
                        self.assertLess(float(chk['absolute_difference']),1e-49)
                    else:self.assertEqual(d['gap'],'0.0')

    def test_small_discount_first_moment_limit(self):
        p=FPT(.6,-.15,.7,1.1,1e-8)
        moment=mp.mpf(truncated_hit_first_moment(p,65))
        with mp.workdps(50):
            ratio=mp.mpf(positive_gap(p,65)['gap'])/mp.mpf('1e-8')
            self.assertLess(abs(ratio/moment-1),mp.mpf('1e-8'))

    def test_eventual_hit_and_zero_drift_closed_limit(self):
        p=FPT(.5,0,.8,2.,0)
        with mp.workdps(65):
            expected=mp.erfc(mp.mpf('.5')/(mp.mpf('.8')*mp.sqrt(4)))
            self.assertLess(abs(mp.mpf(formula(p,70)['F'])-expected),mp.mpf('1e-60'))
        for drift in [-.3,.4]:
            p=FPT(.4,drift,.7,25000.,.12)
            f=formula(p,70)
            with mp.workdps(60):
                x,mu,sig,q=map(mp.mpf,('.4',str(drift),'.7','.12'))
                G_inf=mp.exp(-(mu+mp.sqrt(mu**2+2*q*sig**2))*x/sig**2)
                F_inf=1 if drift<=0 else mp.exp(-2*mu*x/sig**2)
                self.assertLess(abs(mp.mpf(f['G'])-G_inf),mp.mpf('1e-13'))
                self.assertLess(abs(mp.mpf(f['F'])-F_inf),mp.mpf('1e-13'))

    def test_vanishing_sigma_deterministic_hit(self):
        for sigma in [.06,.025,.01]:
            p=FPT(.25,-.5,sigma,2.,.3)
            ret=formula(p,70)
            self.assertAlmostEqual(float(ret['F']),1.,places=8)
            self.assertAlmostEqual(float(ret['G']),math.exp(-.3*.5),delta=.02)
        p=FPT(.25,.5,.01,1.,.3)
        self.assertLess(float(formula(p,70)['F']),1e-40)

    def test_invalid_domains(self):
        with self.assertRaises(ValueError):
            positive_gap(FPT(.5,0,.6,1.,-.1))
        with self.assertRaises(ValueError):
            positive_gap(FPT(.5,0,.6,1.,.1),dps=4)

class TestSimplifiedObstacle(unittest.TestCase):
    def test_pde_gradient_and_boundary(self):
        for r,d,s,k in [(0.05,.03,.4,.08),(.01,.07,.05,.8),(.3,.001,1.5,.1)]:
            p=SimpleStopping(r,d,s,k)
            for z in [1,1+1e-8,1.1,3,15]:
                with self.subTest(p=p,z=z):
                    out=evaluate(p,z)
                    self.assertLess(float(abs(mp.mpf(out['pde_residual']))),1e-60)
                    self.assertGreaterEqual(float(out['equity']),0)
                    if z==1:
                        self.assertLess(abs(float(out['d_equity_d_asset'])),1e-70)
                        self.assertLess(abs(float(out['equity'])),1e-70)
                    else:
                        derivatives=derivative_check(p,z)
                        self.assertLess(float(derivatives['first_derivative_error']),1e-60)
                        self.assertLess(float(derivatives['second_derivative_error']),1e-60)

    def test_boundary_risk_right_derivative_nonzero(self):
        p=SimpleStopping(.05,.03,.4,.08)
        out=evaluate(p,1.)
        self.assertEqual(out['right_boundary_derivative_C'],'0.0')
        self.assertLess(float(out['right_boundary_derivative_Q']),0.)

    def test_bad_parameters_fail_closed(self):
        with self.assertRaises(ValueError):evaluate(SimpleStopping(.05,.03,0.,.08),2.)
        with self.assertRaises(ValueError):evaluate(SimpleStopping(.05,.03,.3,.08),.99)

if __name__=='__main__':unittest.main()
