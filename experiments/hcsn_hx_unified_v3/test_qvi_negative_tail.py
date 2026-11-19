"""P0 scalar renewal far-left-tail regression; no global QVI certification."""

from decimal import Decimal, localcontext
import math
import random
import unittest

from .stopping import (Stop, qvi, regenerative_obstacle,
                       regenerative_value)


class QviNegativeTailTests(unittest.TestCase):
    def test_exact_parent_failure_witness_recovers_finite_obstacle(self):
        # For rho=1/2 and sigma=1, kappa=1 exactly. The arbitrary
        # fixed policy b=2 (not a claimed optimal boundary) gives
        # V(x)=exp(x)/(exp(2)-1) below b and D=1.
        p=Stop(0.,1.,.5,1.,0.,0.)
        with localcontext() as ctx:
            ctx.prec=100
            denominator=Decimal(2).exp()-1
            for x in (-36.,-36.25,-70.,-710.,-1000.,-4096.):
                with self.subTest(x=x):
                    xx=Decimal(str(x))
                    independent=xx-1+(1-xx.exp())/denominator
                    actual=regenerative_obstacle(p,x,boundary=2.)
                    self.assertTrue(math.isfinite(actual))
                    self.assertAlmostEqual(actual,float(independent),delta=2e-12)
                    report=qvi(p,x,boundary=2.)
                    self.assertEqual(report['fire'],False)
                    self.assertEqual(report['obstacle'],actual)
                    self.assertLessEqual(report['obstacle'],0.)
                    self.assertLessEqual(abs(report['generator']),1e-12)

    def test_far_tail_with_positive_refractory_keeps_reset_semantics(self):
        p=Stop(.03,1.,.5,1.,0.,2.)
        b=2.
        for x in (-70.,-750.,-1000.):
            with self.subTest(x=x):
                v=regenerative_value(p,x,boundary=b)
                reset_v=regenerative_value(p,p.reset,boundary=b)
                independent=math.fsum((x-p.cost,p.delay_discount*reset_v,-v))
                self.assertAlmostEqual(regenerative_obstacle(p,x,boundary=b),
                                       independent,delta=2e-12)

    def test_transition_around_tail_switch_is_continuous(self):
        p=Stop(0.,1.,.5,1.,0.,0.)
        for x in (-36.0000001,-36.,-35.9999999):
            with self.subTest(x=x):
                out=regenerative_obstacle(p,x,boundary=2.)
                # Independent formula valid for every x below 2.
                expected=math.fsum((x-1.,
                                    (1.-math.exp(x))/math.expm1(2.)))
                self.assertAlmostEqual(out,expected,delta=1e-12)


    def test_seeded_parameter_tail_panel_against_independent_decimal(self):
        rng=random.Random(2026103122)
        with localcontext() as ctx:
            ctx.prec=100
            dec=Decimal.from_float
            for index in range(128):
                p=Stop(rng.uniform(-.4,.4),10**rng.uniform(-.5,.5),
                       10**rng.uniform(-1.5,.2),1.,0.,
                       rng.choice((0.,.2,1.7)))
                b=1.+1./p.kappa
                x=-(rng.uniform(50.,2000.)+p.discount*p.refractory)/p.kappa
                k,bd,xd,cd,rd=(dec(p.kappa),dec(b),dec(x),dec(p.cost),
                               dec(p.reset))
                delay=(-(dec(p.discount)*dec(p.refractory))).exp()
                reset_factor=(-(k*(bd-rd))).exp()
                amplitude=(bd-cd)/(1-delay*reset_factor)
                value=amplitude*(-(k*(bd-xd))).exp()
                oracle=float(xd-cd+delay*amplitude*reset_factor-value)
                got=regenerative_obstacle(p,x,boundary=b)
                with self.subTest(index=index):
                    self.assertTrue(math.isfinite(got))
                    self.assertLessEqual(abs(got-oracle),
                                         2e-12+2e-15*abs(oracle))
                    self.assertLessEqual(got,0.)

if __name__=='__main__':
    unittest.main()
