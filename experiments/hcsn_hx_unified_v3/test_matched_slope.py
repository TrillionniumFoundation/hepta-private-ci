"""P1 preregistration instrumentation tests, NOT mechanism superiority tests."""

import math
import unittest

from .matched_slope import (hx_log_asset_curve, match_local_slope,
                            ordinary_sigmoid)


class GenericLocalSlopeTests(unittest.TestCase):
    def test_positive_and_negative_channel_derivatives_match_signed_slope(self):
        ordinary=lambda z: ordinary_sigmoid(0.7*z-0.2)
        channels=(lambda z: math.exp(.4*z),
                  lambda z: math.exp(-.4*z),
                  lambda z: z*z+1)
        for curve in channels:
            with self.subTest(curve=curve):
                m=match_local_slope(curve,ordinary,anchor=.55)
                self.assertLess(abs(m.calibrated(curve(.55))-ordinary(.55)),1e-12)
                self.assertLess(abs(m.scale*m.channel_slope-m.ordinary_slope),1e-12)
                self.assertLess(m.stencil_rel_disagreement,1e-5)
        self.assertLess(match_local_slope(channels[1],ordinary,anchor=.55).scale,0)

    def test_linear_affine_channel_identity(self):
        channel=lambda z: 3*z+1
        ordinary=lambda z: -2*z+5
        m=match_local_slope(channel,ordinary,anchor=.9)
        for z in (-3,0,.1,3):
            self.assertAlmostEqual(m.calibrated(channel(z)),ordinary(z),places=9)

    def test_curvature_mismatch_is_not_claimed_as_equivalence(self):
        ordinary=lambda z: ordinary_sigmoid(z)
        channel=lambda z: math.exp(z)
        m=match_local_slope(channel,ordinary,anchor=0.)
        # Local value/slope equality alone does not match curvature or a task.
        self.assertGreater(abs(m.calibrated(channel(1))-ordinary(1)),.05)

    def test_near_zero_slope_rejected(self):
        for curve in (lambda z: 1., lambda z: 1+1e-14*z):
            with self.assertRaises(ArithmeticError):
                match_local_slope(curve,ordinary_sigmoid,anchor=.5)
        with self.assertRaises(ArithmeticError):
            match_local_slope(ordinary_sigmoid,lambda z: 1.,anchor=.5)

    def test_kink_and_jump_rejected(self):
        for curve in (lambda z: abs(z)+1,
                      lambda z: 1 if z>=0 else -1):
            with self.assertRaises(ArithmeticError):
                match_local_slope(curve,ordinary_sigmoid,anchor=0.)

    def test_bad_input_or_domain_rejected(self):
        for kw in ({'step':0},{'step':math.nan},{'anchor':math.inf},
                   {'slope_floor':-1},{'relative_tolerance':2},
                   {'maximum_abs_scale':0}):
            with self.subTest(kw=kw),self.assertRaises(ValueError):
                match_local_slope(math.exp,ordinary_sigmoid,anchor=.1,**{k:v for k,v in kw.items() if k!='anchor'}) if 'anchor' not in kw else match_local_slope(math.exp,ordinary_sigmoid,anchor=kw['anchor'])
        with self.assertRaises(ValueError):
            match_local_slope(lambda z: math.sqrt(z),ordinary_sigmoid,anchor=.001,step=.001)
        with self.assertRaises(ArithmeticError):
            match_local_slope(lambda z: 1e-9*z,ordinary_sigmoid,anchor=.1,
                              slope_floor=1e-12,maximum_abs_scale=1e3)

    def test_financial_adapter_rejects_invalid_channel(self):
        with self.assertRaises(ValueError):
            hx_log_asset_curve(None,'not-a-channel')


class HXFinancialIntegrationTests(unittest.TestCase):
    def test_nominal_hx_channels_slope_match_without_state_clipping(self):
        from .hx import HX
        p=HX()
        for channel in ('call','risk','survival','margin'):
            with self.subTest(channel=channel):
                fn=hx_log_asset_curve(p,channel)
                m=match_local_slope(fn,ordinary_sigmoid,anchor=.45,step=.0005)
                self.assertLess(abs(m.calibrated(fn(.45))-ordinary_sigmoid(.45)),1e-10)
                self.assertLess(abs(m.scale*m.channel_slope-m.ordinary_slope),1e-10)

    def test_negative_equity_and_near_boundary_are_denied(self):
        from .hx import HX
        p=HX(sale_fraction=.2)
        bad=hx_log_asset_curve(p,'call',boundary_exclusion=1e-5)
        with self.assertRaises(ValueError):
            bad(math.log(1.01))
        normal=hx_log_asset_curve(HX(),'risk')
        with self.assertRaises(ValueError):
            normal(0.)
        with self.assertRaises(ValueError):
            match_local_slope(normal,ordinary_sigmoid,anchor=.0011,step=.0005)


if __name__=='__main__':
    unittest.main()
