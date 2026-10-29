"""Independent contract, sampling and derivative checks before confirmation."""

from dataclasses import replace
import math
import unittest

import numpy as np
from scipy.integrate import quad

from experiments.first_passage_adaptive.thresholds import (
    ThresholdContext, execute, named_noise, renewal_value,
)
from experiments.first_passage_adaptive.threshold_policies import (
    feature_matrix, ordinary_thresholds, plan_context,
)


class ThresholdContractTest(unittest.TestCase):
    def setUp(self):
        self.context = ThresholdContext(.9, .6, .18, .4, 3.5, 3, .2, .07)

    def test_value_against_independent_first_hit_density_integrals(self):
        c = self.context
        for b in [.1, .7, 1.8, 3.7]:
            expected = 0.0
            for n in range(1, c.budget+1):
                a, hold, q = n*b, (n-1)*c.refractory, c.cancel_rate+c.discount

                def density(t):
                    return a/(c.sigma*math.sqrt(2*math.pi*t**3))*math.exp(
                        -(a-c.mu*t)**2/(2*c.sigma**2*t)-q*(t+hold))

                expected += quad(density, 0, c.horizon-hold,
                                 epsabs=1e-11, epsrel=1e-11)[0]*(b-c.cost)
            self.assertAlmostEqual(float(renewal_value(b, [c])[0]), expected, places=10)

    def test_threshold_derivative_and_refractory_cancellation(self):
        c = self.context
        for b in [.2, .8, 1.5, 3.9]:
            _, gradient = renewal_value(b, [c], derivative=True)
            h = 1e-5
            fd = (renewal_value(b+h, [c])-renewal_value(b-h, [c]))/(2*h)
            np.testing.assert_allclose(gradient, fd, rtol=2e-8, atol=1e-9)
        slow = replace(c, refractory=1.2)
        self.assertLess(renewal_value(.9, [slow])[0], renewal_value(.9, [c])[0])

    def test_sampler_matches_value_and_budget(self):
        c = self.context
        noise = named_noise(c, seed_base=7301, fit_seed=1, context_index=0, repeats=80000)
        for b in [.8, 1.7]:
            result = execute(b, c, noise)
            mean = result["utility"].mean()
            se = result["utility"].std(ddof=1)/math.sqrt(len(result["utility"]))
            self.assertLess(abs(mean-renewal_value(b, [c])[0]), 5*se+1e-4)
            self.assertTrue(np.all(result["hits"] <= c.budget))
            budget = result["terminal"] == "BUDGET"
            self.assertTrue(np.all(result["hits"][budget] == c.budget))
            self.assertTrue(np.all(result["last_hit_time"][result["hits"] > 0] <= c.horizon))

    def test_stop_and_early_cancellation_execute_no_hit(self):
        c = self.context
        noise = named_noise(c, seed_base=7302, fit_seed=1, context_index=0, repeats=20)
        stopped = execute(0, c, noise)
        self.assertTrue(np.all(stopped["utility"] == 0))
        self.assertTrue(np.all(stopped["terminal"] == "STOP"))
        noise["cancellation"][:] = 0
        cancelled = execute(.9, c, noise)
        self.assertTrue(np.all(cancelled["hits"] == 0))
        self.assertTrue(np.all(cancelled["terminal"] == "CANCEL"))
        noise["branch"][0, 0] = np.nan
        with self.assertRaises(ValueError):
            execute(.9, c, noise)

    def test_planner_and_ordinary_use_context(self):
        c = self.context
        selected, _ = plan_context(c, (.03, 4))
        dense = np.linspace(.03, 4, 1001)
        values = renewal_value(dense, [c]*len(dense))
        self.assertGreaterEqual(renewal_value(selected, [c])[0], values.max()-1e-8)
        contexts = [c, replace(c, cost=.8), replace(c, horizon=1.0), replace(c, budget=1)]
        features, center, scale = feature_matrix(contexts)
        weights = np.zeros(features.shape[1])
        weights[[0, 4, 5, 6]] = [-1., .3, .4, -.2]
        model = {"center": center, "scale": scale, "weights": weights}
        thresholds = ordinary_thresholds(model, contexts, (.03, 4))
        self.assertEqual(len(set(np.round(thresholds, 9))), 4)


if __name__ == "__main__":
    unittest.main()
