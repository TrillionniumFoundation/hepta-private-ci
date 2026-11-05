"""Independent finite enumerations for the paid-reset study's key identities."""

import itertools
import unittest
from unittest.mock import patch

import numpy as np

from .paid_study import GRID, PROTOCOL, allocate, known_mean, outcomes, predict


class PaidStudyTests(unittest.TestCase):
    def test_support_and_negative_controls_cover_the_entire_finite_law(self):
        x = np.repeat(np.linspace(-1, 1, GRID), 2)
        e = np.tile([-1, 1], GRID)
        means = []
        for task in range(3):
            candidate, baseline, d = outcomes(task, x, e)
            self.assertTrue(np.all((candidate >= 0) & (candidate <= 1)))
            self.assertTrue(np.all((baseline >= 0) & (baseline <= 1)))
            means.append(d.mean())
        self.assertLess(means[0], 0)
        self.assertGreater(means[1], 0)
        self.assertAlmostEqual(means[2], 0, places=15)

    def test_finite_bank_variance_from_independent_exhaustive_outcomes(self):
        m, n = 2, 3
        beta = 2*n/(m+n)
        estimates = []
        for signs in itertools.product((-1., 1.), repeat=2*m+n):
            z, noise, reset = np.split(np.asarray(signs), (m, 2*m))
            estimates.append(np.mean(2*z + noise - beta*z) + beta*np.mean(reset))
        self.assertAlmostEqual(np.mean(estimates), 0)
        expected = (5 - 4*beta + beta*beta)/m + beta*beta/n
        self.assertAlmostEqual(np.mean(np.square(estimates)), expected)
        # Reusing each paired reset as its own reset-mean bank cancels the CV.
        self.assertLess(expected, 5/m)

    def test_integer_allocation_matches_full_two_count_search(self):
        d, h = np.array([1., 2., 3., 1.]), np.array([1., 1., 2., 0.])
        with patch.dict(PROTOCOL, budget=32.):
            result = allocate(d, h, setup=3., price=0.1)
        v, c, z = result["pilot_moments"]
        candidates = [v/29]
        for m in range(2, 30):
            for n in range(2, 243):
                if 3 + 1.1*m + 0.12*n <= 32 + 1e-12:
                    b = c/z*n/(m+n)
                    candidates.append((v-2*b*c+b*b*z)/m+b*b*z/n)
        self.assertAlmostEqual(result["risk"], min(candidates), places=12)

    def test_closed_polynomial_reset_mean_matches_full_law(self):
        for p in ([0.2, 0.3], [0.2, -0.3, 0.4, -0.5]):
            model = {"method": f"poly{len(p)-1}", "parameters": p}
            mean, _, calls = known_mean(model)
            self.assertAlmostEqual(mean, predict(model, np.linspace(-1, 1, GRID)).mean())
            self.assertEqual(calls, 0)


if __name__ == "__main__":
    unittest.main()
