"""P1 matched-output precision regression; NO inference or causal winner claim."""
import math
import unittest

from .matched_slope import match_local_slope, ordinary_sigmoid, hx_log_asset_curve
from .hx import HX


class MatchedRoundoffGateTests(unittest.TestCase):
    def test_sigmoid_anchor_mismatch_refused_even_if_stencils_agree(self):
        # The original exact-source implementation accepts the two derivative
        # step estimates but returns ~.5312+1e-5 instead of the anchor value.
        channel=lambda z: 1e12+z
        with self.assertRaisesRegex(ArithmeticError,'roundoff|anchor'):
            match_local_slope(channel,ordinary_sigmoid,anchor=.125,step=.001)

    def test_large_bias_erases_half_point_matched_value(self):
        # Both affine functions are differentiable and have resolved slopes
        # for this step. Old code returned 0 for an ordinary target of 0.5.
        channel=lambda z: 1e18+z
        ordinary=lambda z: .5+.25*z
        with self.assertRaisesRegex(ArithmeticError,'anchor'):
            match_local_slope(channel,ordinary,anchor=0.,step=1e6)

    def test_well_resolved_bias_and_signed_slopes_survive(self):
        ordinary=lambda z: ordinary_sigmoid(z)
        for scale in (1.,-1.):
            channel=lambda z: 100.+scale*z
            m=match_local_slope(channel,ordinary,anchor=.125,step=.001)
            self.assertLessEqual(abs(m.calibrated(channel(.125))-ordinary(.125)),1e-12)
            self.assertEqual(math.copysign(1,m.scale),math.copysign(1,scale))
            self.assertLess(m.roundoff_rel_floor,0.005)

    def test_real_hx_financial_channels_remain_compatible(self):
        p=HX()
        for kind in ('call','risk','survival','margin'):
            with self.subTest(kind=kind):
                channel=hx_log_asset_curve(p,kind)
                m=match_local_slope(channel,ordinary_sigmoid,anchor=.45,step=.0005)
                self.assertLess(abs(m.calibrated(channel(.45))-ordinary_sigmoid(.45)),1e-12)
                self.assertLess(m.roundoff_rel_floor,0.005)


if __name__ == '__main__':
    unittest.main()
