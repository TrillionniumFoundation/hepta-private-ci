"""Independent limits, pathwise Monte Carlo and split/causal renewals."""
import math
import random
import unittest

from .time_varying_refractory_reference import (
    InhomogeneousRenewalError, expected_renewals,
)
from .deterministic_refractory_reference import constant_rate_stats, PathState, advance_path


class InhomogeneousRenewalTests(unittest.TestCase):
    def test_zero_refractory_exact_inhomogeneous_poisson(self):
        rates=[.3,0,3,1.5,.01,0,1.1]
        got=expected_renewals(rates,.1,0)
        exposure=.1*sum(rates)
        self.assertAlmostEqual(got.expected_event_count,exposure,places=14)
        self.assertAlmostEqual(got.first_event_probability,-math.expm1(-exposure),places=14)
        self.assertEqual(got.active_at_end,1.)

    def test_constant_rate_matches_independent_gamma_sum(self):
        lam,T,tau=1.1,6.,.4
        expected=constant_rate_stats(lam,tau,T)
        results=[]
        for n in (300,600,1200):
            got=expected_renewals([lam]*n,T/n,int(tau/(T/n)))
            results.append(abs(got.expected_event_count-expected.expected_event_count))
            self.assertAlmostEqual(got.first_event_probability,expected.first_fire_probability,places=12)
            self.assertTrue(0<=got.active_at_end<=1)
            self.assertGreaterEqual(got.expected_event_count,got.first_event_probability)
        self.assertLess(results[-1],.0001)
        self.assertGreater(results[0],results[1])
        self.assertGreater(results[1],results[2])

    def test_irregular_rate_change_monte_carlo_independent_event_paths(self):
        # Frozen step intensities correspond to a deliberately time-varying,
        # including silent, physical signal. No data-derived hyperparameters.
        h=.02; k=10
        rates=([.2]*80+[2.4]*90+[0]*60+[.8]*120+[3.1]*50)
        got=expected_renewals(rates,h,k)
        rng=random.Random(202610310701)
        n=16000
        totals=0
        seen=0
        # Independent path generator from exact integrated hazards per segment,
        # not the time-grid renewal approximation being tested.
        for i in range(n):
            state=PathState.initial(rng.randrange(2**63),k*h)
            for rate,length in ((.2,80),(2.4,90),(0.,60),(.8,120),(3.1,50)):
                duration=length*h
                if rate==0.:
                    # Exact no-fire continuation. In this silent segment,
                    # refractory mass ages but integrated hazard does not.
                    from dataclasses import replace
                    state=replace(state,physical_time=state.physical_time+duration,
                        refractory_remaining=max(0.,state.refractory_remaining-duration))
                else:
                    state=advance_path(state,rate,duration)
            totals+=state.fired_count
            seen+=(state.fired_count>0)
        self.assertLess(abs(totals/n-got.expected_event_count),.060)
        self.assertLess(abs(seen/n-got.first_event_probability),.02)
        self.assertGreater(got.expected_event_count,got.first_event_probability+1.5)

    def test_refractory_suppresses_total_not_first_event(self):
        rates=([.25]*200+[1.5]*250+[3.]*200)
        before=expected_renewals(rates,.01,0)
        one=expected_renewals(rates,.01,10)
        long=expected_renewals(rates,.01,90)
        for r in (one,long):
            self.assertAlmostEqual(r.first_event_probability,before.first_event_probability,places=12)
            self.assertLess(r.expected_event_count,before.expected_event_count)
        self.assertLess(long.expected_event_count,one.expected_event_count)

    def test_no_future_suffix_leakage_in_prefix(self):
        first=[.9]*50+[1.7]*50
        a=expected_renewals(first+[.1]*50,.01,15)
        b=expected_renewals(first+[3.1]*50,.01,15)
        self.assertEqual(a.step_expected_counts[:100],b.step_expected_counts[:100])
        self.assertEqual(a.step_end_active[:100],b.step_end_active[:100])
        self.assertNotEqual(a.expected_event_count,b.expected_event_count)

    def test_all_silent_intervals_and_zero_horizon_refusal(self):
        z=expected_renewals([0.]*20,.01,3)
        self.assertEqual((z.first_event_probability,z.expected_event_count,z.active_at_end), (0.,0.,1.))
        with self.assertRaises(InhomogeneousRenewalError):
            expected_renewals([],.01,2)

    def test_nonconforming_grid_and_nonfinite_fail_closed(self):
        for rates,dt,k in (([1.],0,1),([math.inf],.1,1),
                           ([.1,-2.],.1,1),([6.],.1,1),([True],.1,1),
                           ([1.],.1,-1),([1.],.1,1.0)):
            with self.subTest(rates=rates,dt=dt,k=k),self.assertRaises(InhomogeneousRenewalError):
                expected_renewals(rates,dt,k)


if __name__=='__main__':
    unittest.main()
