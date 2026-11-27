"""Independent analytic, quadrature and simulated checks for renewal series."""
import math
import unittest
from scipy.integrate import quad
import numpy as np

from .stopping import Stop, regenerative_boundary_independent, regenerative_value
from .renewal_distance_series import (discounted_first_hit,
    expected_discounted_event_count, expected_discounted_reward,
    UnresolvedRenewal)


class RenewalSeriesTests(unittest.TestCase):
    def test_laplace_fpt_matches_density_quadrature(self):
        for mu in (-.65, 0., .4, 1.2):
            for d in (.3, 1., 2.):
                for rate in (0., .03, .8):
                    for T in (.5, 2., 6.):
                        sigma=.8
                        f=lambda t: (d/(sigma*math.sqrt(2*math.pi*t**3))
                            * math.exp(-((d-mu*t)**2)/(2*sigma*sigma*t)-rate*t))
                        oracle=quad(f,0,T,epsabs=2e-12,epsrel=1e-11,limit=300)[0]
                        actual=discounted_first_hit(d,mu,sigma,rate,T)
                        self.assertAlmostEqual(actual,oracle,delta=3e-9*max(oracle,1e-4))

    def test_event_count_matches_infinite_horizon_qvi_discounted_value(self):
        for mu in (-.8,0.,.5,1.3):
            p=Stop(mu,.8,.13,1.5,.25,.2)
            b=regenerative_boundary_independent(p)
            for x in (p.reset,b-.45,b+.15):
                v,tail=expected_discounted_reward(p,x,b,120,
                    absolute_tail_tolerance=1e-13)
                target=regenerative_value(p,x,boundary=b)
                self.assertLessEqual(v,target+2e-12)
                self.assertAlmostEqual(v,target,delta=max(2e-8,1e-6*abs(target)))
                self.assertLessEqual(tail,1e-13*(b-p.cost))

    def test_finite_horizon_count_vs_monte_carlo(self):
        rng=np.random.default_rng(20261031)
        mu,sigma=.6,.85
        p=Stop(mu,sigma,.16,1.,0.,.35)
        b=1.35
        T=3.5
        analytic=expected_discounted_event_count(p,0.,b,T)
        samples=[]
        for _ in range(20000):
            t=0.0; d=b; acc=0.0
            for __ in range(100):
                t+=float(rng.wald(d/mu,(d/sigma)**2))
                if t>T: break
                acc+=math.exp(-p.discount*t)
                t+=p.refractory; d=b-p.reset
            samples.append(acc)
        mean=float(np.mean(samples))
        stderr=float(np.std(samples,ddof=1)/math.sqrt(len(samples)))
        self.assertLess(abs(mean-analytic.discounted_events),5*stderr+1e-3)
        self.assertLess(analytic.omitted_events_upper_bound,1e-11)

    def test_nonzero_event_at_initial_above_threshold(self):
        p=Stop(-.3,.7,.2,2.,.1,.5)
        b=2.4
        a=expected_discounted_event_count(p,b+.8,b,0.)
        self.assertEqual(a.discounted_events,1.)
        v,_=expected_discounted_reward(p,b+.8,b,0.)
        self.assertAlmostEqual(v,b+.8-p.cost)
        self.assertEqual(expected_discounted_event_count(p,b-.8,b,0.).discounted_events,0.)

    def test_chernoff_truncates_tiny_discount_large_drift(self):
        p=Stop(2.,.5,1e-12,1.,0.,0.)
        b=2.; x=0.; T=2.
        result=expected_discounted_event_count(p,x,b,T,max_terms=40)
        oracle=math.fsum(discounted_first_hit(2.+2.*n,p.drift,p.diffusion,
                        p.discount,T) for n in range(40))
        self.assertLessEqual(abs(oracle-result.discounted_events),
                             result.omitted_events_upper_bound+2e-12)
        self.assertLess(result.terms_evaluated,40)
        self.assertLess(result.omitted_events_upper_bound,1e-11)

    def test_without_refractory_geometric_tail_is_bounded(self):
        p=Stop(.8,.7,.2,1.,0.,0.)
        b=2.0
        a=expected_discounted_event_count(p,.2,b,3.,max_terms=1024)
        self.assertGreater(a.discounted_events,0.)
        self.assertFalse(a.full_finite_series)
        self.assertLessEqual(a.omitted_events_upper_bound,1e-11)

    def test_negative_drift_defective_probability(self):
        d,mu,sig=1.2,-.5,.8
        g=discounted_first_hit(d,mu,sig,0,1000)
        self.assertAlmostEqual(g,math.exp(2*mu*d/(sig*sig)),delta=1e-12)
        p=Stop(mu,sig,.2,1.5,.2,.1)
        b=2.1
        a=expected_discounted_event_count(p,.4,b,50.)
        self.assertLess(a.discounted_events,1.0)

    def test_defective_negative_drift_renewal_against_simulation(self):
        rng=np.random.default_rng(310031)
        p=Stop(-.35,.75,.2,1.1,.1,.25)
        b=1.4; x=.25; T=6.0
        theoretical=expected_discounted_event_count(p,x,b,T)
        weighted=[]
        for _ in range(30000):
            t=0.; distance=b-x; total=0.
            for __ in range(50):
                probability=math.exp(2*p.drift*distance/(p.diffusion**2))
                if rng.random()>=probability: break
                t+=float(rng.wald(distance/abs(p.drift),
                                   (distance/p.diffusion)**2))
                if t>T: break
                total+=math.exp(-p.discount*t)
                t+=p.refractory
                distance=b-p.reset
            weighted.append(total)
        sample=float(np.mean(weighted))
        se=float(np.std(weighted,ddof=1)/math.sqrt(len(weighted)))
        self.assertLess(abs(sample-theoretical.discounted_events),5*se+1e-3)

    def test_loose_vs_tight_truncation_envelope(self):
        p=Stop(.6,.9,.1,1.,.15,0.)
        b=1.3; x=.2; T=4.
        loose=expected_discounted_event_count(p,x,b,T,
             absolute_tail_tolerance=2e-3)
        tight=expected_discounted_event_count(p,x,b,T,
             absolute_tail_tolerance=1e-13)
        self.assertLessEqual(abs(loose.discounted_events-tight.discounted_events),
                             loose.omitted_events_upper_bound + 1e-12)
        self.assertLessEqual(tight.omitted_events_upper_bound,1e-13)

    def test_first_hit_monotonic_horizon(self):
        for mu in (-1.,0.,1.):
            vals=[discounted_first_hit(1.,mu,.6,.1,t) for t in (.1,.5,2.,6.,20.)]
            self.assertTrue(all(x<=y for x,y in zip(vals,vals[1:])))
            self.assertTrue(all(0<=x<=1 for x in vals))

    def test_reject_out_of_domain_instead_of_clipping(self):
        for args in [(1.,0.,0.,0.,1.),(-1.,0.,1.,0.,1.),(1.,0.,1.,-1.,1.),
                     (1.,0.,1.,0.,-1.),(math.nan,0.,1.,0.,1.)]:
            with self.assertRaises(UnresolvedRenewal): discounted_first_hit(*args)
        p=Stop(1000.,1e-6,1e-12,1.,0.,0.)
        with self.assertRaises(UnresolvedRenewal):
            expected_discounted_event_count(p,0.,2.,1.,max_terms=8)

    def test_analytic_tail_starts_at_correct_event_index(self):
        p=Stop(.5,1.,.12,1.,.1,.05)
        b=1.5
        # Deliberately truncated series must be rejected if omitted tail > budget.
        with self.assertRaises(UnresolvedRenewal):
            expected_discounted_event_count(p,0.,b,10.,max_terms=1)
        full=expected_discounted_event_count(p,0.,b,10.)
        self.assertGreater(full.terms_evaluated,1)

if __name__=='__main__': unittest.main()
