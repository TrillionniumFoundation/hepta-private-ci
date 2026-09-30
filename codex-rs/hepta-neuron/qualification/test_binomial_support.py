"""Numerical and non-vacuity regressions for finite-sample diagnostics."""
import math
import unittest
from binomial_support import error_upper_bound, support_report


class BinomialSupportTests(unittest.TestCase):
    def test_zero_errors_are_not_zero_risk(self):
        self.assertAlmostEqual(error_upper_bound(0, 64), 1 - .05 ** (1 / 64))
        self.assertGreater(error_upper_bound(0, 64), .04)

    def test_no_trials_are_not_a_pass(self):
        result = support_report(ood_errors=0, ood_trials=0, decision_errors=0, decision_trials=0)
        self.assertIsNone(result['ood']['upper'])
        self.assertFalse(result['count_bounds_met'])

    def test_exact_small_population_inversion(self):
        for n in range(2, 25):
            for k in range(1, n):
                p = error_upper_bound(k, n, .025)
                cdf = sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))
                self.assertAlmostEqual(cdf, .025, delta=1e-7)

    def test_minimum_support_boundary(self):
        result = support_report(ood_errors=0, ood_trials=64, decision_errors=0, decision_trials=96)
        self.assertFalse(result['count_bounds_met'])
        n = result['zero_error_minimum_independent_trials_per_population']
        self.assertTrue(support_report(ood_errors=0, ood_trials=n, decision_errors=0, decision_trials=n)['count_bounds_met'])
        self.assertFalse(support_report(ood_errors=0, ood_trials=n-1, decision_errors=0, decision_trials=n)['count_bounds_met'])

    def test_observed_errors_increase_upper_limit(self):
        limits = [error_upper_bound(k, 100) for k in range(101)]
        self.assertEqual(limits, sorted(limits))
        self.assertEqual(limits[-1], 1.0)

    def test_large_population_numerically_finite(self):
        for k in (0, 1, 400, 500000, 999999):
            value = error_upper_bound(k, 1000000)
            self.assertTrue(math.isfinite(value))
            self.assertTrue(k / 1000000 <= value <= 1)

    def test_invalid_counts_and_probabilities(self):
        for k, n, alpha in [(True,1,.05),(0,True,.05),(-1,64,.05),(65,64,.05),(0,1000001,.05),(0,1,0),(0,1,float('nan')),(0,1,True)]:
            with self.assertRaises(ValueError): error_upper_bound(k,n,alpha)

    def test_even_good_counts_do_not_issue_trust(self):
        result = support_report(ood_errors=0, ood_trials=10000, decision_errors=0, decision_trials=10000)
        self.assertTrue(result['count_bounds_met'])
        for key in ('independence_established','calibration_trust_granted','runtime_selection_eligible','prospective_future_window_evidence','production_activation'):
            self.assertIs(result[key], False)


if __name__ == '__main__': unittest.main()
