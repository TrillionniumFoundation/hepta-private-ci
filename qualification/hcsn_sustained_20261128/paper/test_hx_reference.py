"""Regression checks for the published calibration and the independent renewal reference."""
from dataclasses import replace
import math
import unittest

import numpy as np
from scipy.integrate import quad
from scipy.special import ndtr

from hx_reference import Renewal, hit, hit_gradient, paper_row, sample_counts


class CalibrationTest(unittest.TestCase):
    def test_published_spreads_and_liquidity_order(self):
        rows = [paper_row(xi) for xi in (1, 2, 4)]
        np.testing.assert_allclose([r["spread_bps"] for r in rows],
                                   [330., 499.6, 853.], rtol=0, atol=.36)
        self.assertTrue(np.all(np.diff([r["boundary"] for r in rows]) > 0))
        self.assertTrue(np.all(np.diff([r["equity_at_100"] for r in rows]) < 0))
        self.assertTrue(np.all(np.diff([r["one_year_passage"] for r in rows]) > 0))

    def test_zero_liquidity_premium_limit(self):
        zero, near = paper_row(0.), paper_row(1e-7)
        self.assertAlmostEqual(zero["boundary"], 65.0484029360, places=8)
        self.assertLess(abs(zero["boundary"] - near["boundary"]), 3e-7)
        self.assertLess(abs(zero["equity_at_100"] - near["equity_at_100"]), 8e-7)

    def test_one_sided_wall_behavior(self):
        row = paper_row(1)
        self.assertAlmostEqual(row["right_equity_log_curvature"], 927.44652, places=4)
        right = (hit(1e-6, 1., .03355, .23) - 1.) / 1e-6
        self.assertAlmostEqual(row["right_risk_log_slope"], right, places=5)
        self.assertLess(right, -4)
        self.assertEqual(hit(0., 1., .03355, .23), 1.)


class PassageTest(unittest.TestCase):
    def test_density_quadrature(self):
        for drift in (-.12, 0., .15):
            for q in (0., .09):
                x, sigma, t = .24, .3, 1.5
                def density(s):
                    return (x * math.exp(-q*s-(x+drift*s)**2/(2*sigma**2*s))
                            / (sigma * math.sqrt(2*math.pi) * s**1.5))
                expected = quad(density, 0, t, epsabs=1e-12)[0]
                self.assertAlmostEqual(hit(x, t, drift, sigma, q), expected, places=12)

    def test_small_time_and_drift_limits(self):
        self.assertEqual(hit(.2, 0., 0., .3), 0.)
        self.assertEqual(hit(0., 0., 0., .3), 1.)
        self.assertEqual(hit(.2, math.inf, -.2, .3), 1.)
        self.assertAlmostEqual(hit(.2, math.inf, .15, .3), math.exp(-2*.2*.15/.3**2))
        self.assertAlmostEqual(hit(.2, 1., 0., .3), 2*ndtr(-.2/.3))
        self.assertEqual(hit(1., 1e-12, 0., .3), 0.)
        # At the deterministic travel time, the reflected normal has an
        # exponentially large prefactor if computed without tail scaling.
        self.assertAlmostEqual(hit(100., 1., -100., .1), .50019947109, places=9)

    def test_spatial_slope_both_drift_signs(self):
        for drift in (-.3, 0., .3):
            step, x, t, s = 1e-6, .14, .9, .25
            central = (hit(x+step,t,drift,s) - hit(x-step,t,drift,s)) / (2*step)
            self.assertAlmostEqual(hit_gradient(x,t,drift,s)[0], central, places=8)


class RenewalTest(unittest.TestCase):
    def test_single_event_and_exact_refractory_end(self):
        cell = Renewal(lag=.25)
        self.assertEqual(cell.count_and_gradient(0)[0], 0.)
        for t in (.1, .25):
            self.assertEqual(cell.count_and_gradient(t)[0], hit(cell.initial,t,cell.drift,cell.sigma))
        self.assertGreater(cell.count_and_gradient(1.)[0], hit(cell.initial,1.,cell.drift,cell.sigma))

    def test_six_gradients_including_varying_delay(self):
        for drift in (-.1, 0., .1):
            cell, t, step = Renewal(drift=drift), .957, 1e-6
            _, analytic = cell.count_and_gradient(t)
            numeric = []
            for name, value in vars(cell).items():
                hi = replace(cell, **{name:value+step}).count_and_gradient(t)[0]
                lo = replace(cell, **{name:value-step}).count_and_gradient(t)[0]
                numeric.append((hi-lo)/(2*step))
            numeric.append((cell.count_and_gradient(t+step)[0]-cell.count_and_gradient(t-step)[0])/(2*step))
            np.testing.assert_allclose(numeric, analytic, rtol=2e-8, atol=2e-9)

    def test_long_run_uses_initial_and_reset_separately(self):
        cell = Renewal(initial=.1, reset=.3)
        p0, pr = [math.exp(-2*cell.drift*x/cell.sigma**2) for x in (.1,.3)]
        total, rate = cell.long_run()
        self.assertAlmostEqual(total, p0/(1-pr))
        self.assertEqual(rate, 0.)
        self.assertEqual(replace(cell, drift=0.).long_run(), (math.inf, 0.))
        self.assertEqual(replace(cell, drift=-.1).long_run(), (math.inf, 1/(.05+.3/.1)))

    def test_independent_cycle_sampling(self):
        for mu in (-.08, 0., .03355):
            cell = Renewal(drift=mu)
            counts = sample_counts(cell, [1.,5.], 30_000, 873)
            for t, observed in zip((1.,5.), counts):
                expected, _ = cell.count_and_gradient(t)
                self.assertLess(abs(observed.mean()-expected), 4.5*observed.std(ddof=1)/math.sqrt(len(observed)))
            self.assertTrue(np.all(counts[1] >= counts[0]))


if __name__ == "__main__":
    unittest.main()
