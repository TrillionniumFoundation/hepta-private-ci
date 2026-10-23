"""Analytic evidence for fixed-checkpoint, conditional and paired inference."""

import math
import unittest

import numpy as np

from audit_statistics import match_report, paired_statistics, percentile


class StatisticsAuditTests(unittest.TestCase):
    def test_root_conditioning_precedes_averaging(self):
        returns = np.zeros((1, 2, 2, 4))
        returns[:, 1] = -2.
        result = paired_statistics(returns, -returns, 2., 16)
        np.testing.assert_array_equal(result['sampled_J'], [-1.] * 4)
        pooled_ce = -math.log((1 + math.exp(4)) / 2) / 2
        self.assertLess(pooled_ce, result['sampled_J'][0])
        np.testing.assert_array_equal(result['bootstrap_J'], np.full((16, 4), -1.))

    def test_fixed_seed_effects_are_not_resampled(self):
        returns = np.zeros((2, 2, 3, 4))
        returns[0, :, :, 0], returns[1, :, :, 0] = .25, -.25
        result = paired_statistics(returns, -returns, 2., 32)
        differences = result['bootstrap_J'][:, 0] - result['bootstrap_J'][:, 1]
        np.testing.assert_array_equal(differences, np.zeros(32))

    def test_paired_cash_translation_has_constant_contrast(self):
        base = np.array([[-.1, -.2, -.8], [-.3, -.9, -.6]])
        returns = np.stack([base + shift for shift in (0., -.01, .02, .1)], axis=-1)[None]
        result = paired_statistics(returns, -returns, 2., 64)
        difference = result['bootstrap_J'][:, 0] - result['bootstrap_J'][:, 1]
        np.testing.assert_allclose(difference, .01, rtol=0, atol=1e-14)
        self.assertAlmostEqual(percentile([1., 3., 6., 10.], .25), 2.5)
        self.assertEqual(percentile([1., 3., 6., 10.], 1.), 10.)

    def test_report_corruption_and_nonfinite_evidence_rejected(self):
        with self.assertRaises(AssertionError):
            match_report({'ci': [.2, .4]}, {'ci': [.1, .4]})
        with self.assertRaises(AssertionError):
            match_report({'passed': 1}, {'passed': True})
        with self.assertRaises(AssertionError):
            paired_statistics(np.full((1, 1, 2, 4), np.nan), np.zeros((1, 1, 2, 4)), 2., 4)


if __name__ == '__main__':
    unittest.main()
