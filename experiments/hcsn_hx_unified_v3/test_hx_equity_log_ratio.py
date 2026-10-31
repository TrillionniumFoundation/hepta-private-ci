"""Closed-form HX equity finite-domain ratio guard; research-only."""
import math
import unittest
from unittest.mock import patch

from . import hx
from .hx import (HX, _log_asset_ratio, boundary, equity_closed,
                 equity_resolvent, mechanism_channels)


class ClosedEquityLogRatioTests(unittest.TestCase):
    def test_extreme_finite_ratio_does_not_silently_nan(self):
        p=HX()
        for asset,b in ((1e308,1e-308),(1e308,1e-100),(1e200,1e-200)):
            with self.subTest(asset=asset,boundary=b):
                self.assertTrue(math.isinf(asset/b))
                self.assertTrue(math.isfinite(_log_asset_ratio(asset,b)))
                e=equity_closed(p,asset,b)
                self.assertTrue(math.isfinite(e))
                self.assertAlmostEqual(e/asset,1.,delta=1e-12)
                channels=mechanism_channels(p,asset,b)
                self.assertEqual(channels.equity,e)
                self.assertEqual(channels.default_probability,0.)
                self.assertEqual(channels.discounted_default_factor,0.)
                self.assertTrue(math.isfinite(channels.rollover_margin))

    def test_regular_domain_retains_independent_financial_resolvent(self):
        for p in (HX(), HX(payout=0.), HX(sale_fraction=0.)):
            b=boundary(p)
            for ratio in (1.001,1.6,4.):
                with self.subTest(p=p,ratio=ratio):
                    asset=b*ratio
                    self.assertEqual(_log_asset_ratio(asset,b),
                                     math.log(asset/b))
                    closed=equity_closed(p,asset,b)
                    independent=equity_resolvent(p,asset,b)
                    self.assertLess(abs(closed-independent),2e-7*(1+abs(closed)))

    def test_negative_equity_obstacle_counterexample_remains_negative(self):
        p=HX(sale_fraction=.2)
        b=boundary(p)
        self.assertLess(equity_closed(p,b*1.01,b),0.)

    def test_unresolved_equity_is_refused_not_clamped(self):
        p=HX()
        with patch.object(hx,'_A',return_value=math.nan):
            with self.assertRaises(ArithmeticError):
                equity_closed(p,1.6,1.)


if __name__=='__main__':
    unittest.main()
