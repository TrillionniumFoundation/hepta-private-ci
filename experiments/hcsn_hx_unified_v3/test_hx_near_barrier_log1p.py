"""Research-only regression for a one-ULP log-ratio/first-passage false result.

The mpmath path recomputes the Brownian first-passage laws from the original
finite binary64 inputs; it does not call the source log-ratio helper.
"""
import math
import random
import unittest

import mpmath as mp

from experiments.hcsn_hx_unified_v3.hx import (
    HX, _log_asset_ratio, default_probability, discounted_default_factor,
)


def independent_first_passage(p: HX, asset: float, boundary: float, tau: float):
    with mp.workdps(110):
        rate, payout = mp.mpf(p.rate), mp.mpf(p.payout)
        vol = mp.mpf(p.volatility)
        q = rate + mp.mpf(p.shock_intensity) * mp.mpf(p.sale_fraction)
        a = (rate - payout - vol * vol / 2) / (vol * vol)
        zhat = mp.sqrt(a*a + 2*q/(vol*vol))
        v = mp.log(mp.mpf(asset) / mp.mpf(boundary))
        u = vol * mp.sqrt(mp.mpf(tau))
        phi = lambda z: mp.erfc(-z/mp.sqrt(2))/2
        f = phi((-v-a*u*u)/u) + mp.exp(-2*a*v)*phi((-v+a*u*u)/u)
        g = (mp.exp((-a+zhat)*v)*phi((-v-zhat*u*u)/u)
             + mp.exp((-a-zhat)*v)*phi((-v+zhat*u*u)/u))
        return float(f), float(g), float(v)


class HXNearBarrierLog1pGate(unittest.TestCase):
    def test_one_ulp_first_passage_against_independent_mpmath(self):
        p = HX()
        # For these inputs both rounded F/G pass the inherited joint
        # ordering guard. Other legitimate inputs can be refused by it.
        for boundary in (0.1, 0.3, 0.7, 1e308):
            asset = math.nextafter(boundary, math.inf)
            for tau in (1e-30, 1e-29, 1e-28):
                with self.subTest(boundary=boundary, tau=tau):
                    f, g, v = independent_first_passage(p, asset, boundary, tau)
                    self.assertGreater(v, 0)
                    self.assertAlmostEqual(
                        _log_asset_ratio(asset, boundary), v, delta=8e-30,
                    )
                    self.assertAlmostEqual(
                        default_probability(p, asset, tau, boundary), f, delta=2e-13,
                    )
                    self.assertAlmostEqual(
                        discounted_default_factor(p, asset, tau, boundary), g,
                        delta=2e-13,
                    )

    def test_log_ratio_near_barrier_across_extreme_scales(self):
        for boundary in (0.1, 0.3, 0.7, 1e-20, 1e20, 1e308):
            asset = math.nextafter(boundary, math.inf)
            with self.subTest(boundary=boundary):
                _, _, v = independent_first_passage(HX(), asset, boundary, 1e-29)
                self.assertAlmostEqual(_log_asset_ratio(asset, boundary), v, delta=8e-30)

    def test_joint_fpt_guard_remains_fail_closed(self):
        p = HX()
        for boundary in (1e-20, 1e20):
            with self.subTest(boundary=boundary):
                asset = math.nextafter(boundary, math.inf)
                with self.assertRaisesRegex(ArithmeticError, "ordering unresolved"):
                    default_probability(p, asset, 1e-30, boundary)

    def test_seeded_one_ulp_log_ratio_wide_exponents(self):
        rng = random.Random(20261031)
        with mp.workdps(110):
            for i in range(1200):
                boundary = math.ldexp(rng.uniform(0.5, 1.0),
                                       rng.randrange(-980, 980))
                asset = math.nextafter(boundary, math.inf)
                truth = float(mp.log(mp.mpf(asset) / mp.mpf(boundary)))
                observed = _log_asset_ratio(asset, boundary)
                with self.subTest(case=i):
                    self.assertGreater(truth, 0)
                    self.assertLess(abs(observed/truth-1), 2e-13)

    def test_regular_quotient_path_is_byte_compatible(self):
        for asset, boundary in ((1.23, .1), (1.0001, 1.), (1e300, 1e100), (1.01, 1.)):
            with self.subTest(asset=asset, boundary=boundary):
                self.assertEqual(_log_asset_ratio(asset, boundary), math.log(asset/boundary))

    def test_ratio_overflow_still_has_finite_log(self):
        self.assertEqual(
            _log_asset_ratio(1e308, 1e-308), math.log(1e308)-math.log(1e-308),
        )

    def test_at_or_below_barrier_endpoint(self):
        p = HX()
        for asset in (.09999999999999999, .1):
            with self.subTest(asset=asset):
                self.assertEqual(default_probability(p, asset, 1e-30, .1), 1.)
                self.assertEqual(discounted_default_factor(p, asset, 1e-30, .1), 1.)
        self.assertEqual(default_probability(p, math.nextafter(.1, math.inf), 0., .1), 0.)


if __name__ == "__main__":
    unittest.main()
