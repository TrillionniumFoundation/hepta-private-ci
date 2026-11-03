"""P1: independently check signed derivatives and reject fake equality."""
from dataclasses import replace
import math
import random
import unittest

from .perpetual_put_qvi_reference import GBMPut
from .local_slope_calibration import (
    UnresolvedCalibration,channel_at,affine_match,
)


class LocalSlopeCalibrationTests(unittest.TestCase):
    def setUp(self):
        self.p=GBMPut(.08,.02,.23,1.)
        self.anchor=1.15*self.p.boundary

    def test_call_risk_margin_derivatives_against_independent_finite_differences(self):
        for channel in ('call','risk','margin'):
            for anchor in (1.05,1.2,1.8):
                v=anchor*self.p.boundary
                h=1e-5*v
                lhs=channel_at(self.p,v-h,channel)
                rhs=channel_at(self.p,v+h,channel)
                got=channel_at(self.p,v,channel)
                fd=(rhs.value-lhs.value)/(2*h)
                with self.subTest(channel=channel,anchor=anchor):
                    self.assertAlmostEqual(got.signed_dv,fd,
                        delta=2e-5*max(1.,abs(got.signed_dv)))

    def test_signed_anchor_alignment_for_all_three_channels(self):
        for channel in ('call','risk','margin'):
            f=channel_at(self.p,self.anchor,channel)
            match=affine_match(f,target_value=.25,target_signed_dv=-.35)
            self.assertAlmostEqual(match.forward(f.value),.25,places=12)
            self.assertAlmostEqual(match.gain*f.signed_dv,-.35,places=12)
            h=1e-5*self.anchor
            yminus=match.forward(channel_at(self.p,self.anchor-h,channel).value)
            yplus=match.forward(channel_at(self.p,self.anchor+h,channel).value)
            self.assertAlmostEqual((yplus-yminus)/(2*h),-.35,delta=1e-5)

    def test_slope_sign_is_matched_not_magnitude_only(self):
        f=channel_at(self.p,self.anchor,'risk')
        self.assertLess(f.signed_dv,0)
        gate=affine_match(f,target_value=.8,target_signed_dv=.1)
        self.assertLess(gate.gain,0)
        self.assertAlmostEqual(gate.gain*f.signed_dv,.1,delta=1e-12)

    def test_boundary_flat_call_refused(self):
        for v in (.95*self.p.boundary,self.p.boundary):
            f=channel_at(self.p,v,'call')
            self.assertEqual(f.signed_dv,0)
            with self.assertRaises(UnresolvedCalibration):
                affine_match(f,target_value=.2,target_signed_dv=.5)

    def test_near_threshold_margin_refused_even_with_nonzero_slope(self):
        f=channel_at(self.p,self.p.boundary,'margin')
        with self.assertRaises(UnresolvedCalibration):
            affine_match(f,target_value=.2,target_signed_dv=.5)

    def test_unstable_gain_rejected(self):
        f=channel_at(self.p,self.anchor,'risk')
        with self.assertRaises(UnresolvedCalibration):
            affine_match(f,target_value=0.,target_signed_dv=1e7,max_gain=100)

    def test_invalid_and_degenerate_risk_rejected(self):
        for v,T,sigma in ((0.,1.,.2),(1.,0.,.2),(1.,1.,0.),(math.inf,1.,.2)):
            with self.subTest(v=v,T=T,sigma=sigma),self.assertRaises(UnresolvedCalibration):
                channel_at(self.p,v,'risk',horizon=T,diffusion=sigma)

    def test_training_only_random_anchor_derivatives(self):
        rng=random.Random(20261031)
        for _ in range(120):
            v=self.p.boundary*rng.uniform(1.07,1.8)
            f=channel_at(self.p,v,'margin')
            g=affine_match(f,target_value=rng.uniform(-.5,.5),
                           target_signed_dv=rng.uniform(-1.5,-.1))
            self.assertAlmostEqual(g.gain*f.signed_dv,g.target_signed_dv,places=12)


if __name__=='__main__':
    unittest.main()
