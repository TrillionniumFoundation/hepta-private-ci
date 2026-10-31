"""P0 research-only: independent resolvent must retain adjacent-f64 log distance.

The 110-dps reference uses the exact two input floats; it does not invoke
HX's _log_asset_ratio. scipy.integrate.quad is mocked only to expose the
integration split passed by the actual source. These tests do NOT certify
the complete Green integral, financial obstacle or model deployment.
"""
import math
import random
import unittest
from unittest.mock import patch

import mpmath as mp

from experiments.hcsn_hx_unified_v3 import hx


class EquityResolventOneUlpGate(unittest.TestCase):
    def _source_quadrature_split(self, p, asset, boundary):
        intervals = []

        def zero_integral(_integrand, low, high, **_kwargs):
            intervals.append((low, high))
            return (0.0, 0.0)

        with patch("scipy.integrate.quad", side_effect=zero_integral):
            value = hx.equity_resolvent(p, asset, boundary)
        self.assertEqual(len(intervals), 2)
        self.assertEqual(intervals[0][0], 0.0)
        self.assertEqual(intervals[1][0], intervals[0][1])
        self.assertTrue(math.isfinite(value))
        return intervals[0][1]

    def test_adjacent_float_barrier_has_correct_independent_log_distance(self):
        p = hx.HX()
        boundaries = [0.1, 0.3, 0.7, 1e-20, 1e20, 1e308]
        rng = random.Random(20261031)
        boundaries.extend(10.0 ** rng.uniform(-250, 250) for _ in range(120))
        with mp.workdps(110):
            for boundary in boundaries:
                asset = math.nextafter(boundary, math.inf)
                reference = float(mp.log(mp.mpf(asset) / mp.mpf(boundary)))
                with self.subTest(boundary=boundary):
                    self.assertGreater(reference, 0.0)
                    observed = self._source_quadrature_split(p, asset, boundary)
                    self.assertAlmostEqual(observed, reference, delta=5e-30)

    def test_regular_ratio_path_is_unchanged(self):
        p = hx.HX()
        for boundary, asset in ((0.1, 0.125), (1.0, 1.25),
                                (2.0, 3.0), (1e20, 1.25e20)):
            with self.subTest(boundary=boundary):
                observed = self._source_quadrature_split(p, asset, boundary)
                self.assertEqual(observed, math.log(asset / boundary))

    def test_at_and_below_barrier_still_return_zero_without_quadrature(self):
        p = hx.HX()
        with patch("scipy.integrate.quad") as fake_quad:
            self.assertEqual(hx.equity_resolvent(p, 0.1, 0.1), 0.0)
            self.assertEqual(hx.equity_resolvent(
                p, math.nextafter(0.1, -math.inf), 0.1), 0.0)
            fake_quad.assert_not_called()


if __name__ == "__main__":
    unittest.main()
