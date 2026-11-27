"""Independent bounded-causal, gamma-series and zero-refractory tests."""
import math
import unittest

from scipy.special import gammainc

from .time_varying_refractory_reference import (
    expected_renewals, InhomogeneousRenewalError,
)


def gamma_count(rate, horizon, refractory):
    """E[N_T] = sum_{n>=1} P(Gamma(n,rate)+(n-1)*tau <= T)."""
    if refractory == 0:
        return rate*horizon
    terms=[]
    for n in range(1,math.ceil(horizon/refractory)+1):
        t=horizon-(n-1)*refractory
        if t<=0: break
        terms.append(float(gammainc(n,rate*t)))
    return math.fsum(terms)


class TimeVaryingRefractoryReplayTests(unittest.TestCase):
    def test_zero_refractory_exact_pieces(self):
        rates=[.2,0.,1.3,2.5,0.,.1]
        r=expected_renewals(rates,.1,0)
        expected=.1*sum(rates)
        self.assertAlmostEqual(r.expected_event_count,expected,places=13)
        self.assertAlmostEqual(r.first_event_probability,-math.expm1(-expected),places=13)
        self.assertEqual(r.active_at_end,1.)

    def test_constant_rate_converges_to_independent_gamma_oracle(self):
        rate,T,tau=1.1,6.,.4
        exact=gamma_count(rate,T,tau)
        error=[]
        for n in (300,600,1200):
            g=expected_renewals([rate]*n,T/n,int(tau/(T/n)))
            error.append(abs(g.expected_event_count-exact))
            self.assertAlmostEqual(g.first_event_probability,-math.expm1(-rate*T),places=12)
        self.assertGreater(error[0],error[1])
        self.assertGreater(error[1],error[2])
        self.assertLess(error[-1],1e-5)

    def test_prefix_causality_and_repeated_count_not_first_probability(self):
        prefix=[.1]*60+[2.5]*70
        a=expected_renewals(prefix+[0.]*30,.02,10)
        b=expected_renewals(prefix+[2.4]*30,.02,10)
        self.assertEqual(a.step_expected_counts[:130],b.step_expected_counts[:130])
        self.assertEqual(a.step_end_active[:130],b.step_end_active[:130])
        self.assertGreater(b.expected_event_count,b.first_event_probability)
        self.assertNotEqual(a.expected_event_count,b.expected_event_count)

    def test_refractory_cuts_repeated_rate_but_not_initial_risk(self):
        rates=[1.1]*600
        short=expected_renewals(rates,.01,3)
        long=expected_renewals(rates,.01,100)
        self.assertAlmostEqual(short.first_event_probability,long.first_event_probability,places=12)
        self.assertLess(long.expected_event_count,short.expected_event_count)
        self.assertTrue(0<=long.active_at_end<=1)

    def test_reject_bad_rate_time_budget_and_k(self):
        cases=[([math.inf],.1,0),([.1,-1.],.1,2),([True],.1,2),
               ([.1],0.,3),([3.],.2,2),([], .01,2),([.1],.1,1.5)]
        for args in cases:
            with self.subTest(args=args),self.assertRaises(InhomogeneousRenewalError):
                expected_renewals(*args)


if __name__ == '__main__':
    unittest.main()
