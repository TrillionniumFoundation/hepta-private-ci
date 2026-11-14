"""Independent signed-slope controls for three hypothetical HX channels."""
import math
import unittest

from .signed_anchor_calibration import match_value_and_signed_slope, UnresolvedAnchor


class SignedAnchorTests(unittest.TestCase):
    def test_three_channels_match_signed_first_order_near_training_anchor(self):
        fn={
            'call':lambda v: (v-1.)**2,
            'risk':lambda v: 1/(1+math.exp(v-2.)),
            'margin':lambda v: math.log(v/1.2),
        }
        for channel,f in fn.items():
            with self.subTest(channel=channel):
                target=-.25 if channel=='risk' else .4
                model=match_value_and_signed_slope(channel,f,2.,target_value=.8,target_slope=target)
                self.assertFalse(model.is_global_equivalence)
                self.assertAlmostEqual(model.evaluate(f(2.)),.8,places=12)
                self.assertAlmostEqual(model.gain*model.signed_input_slope,target,places=12)
                delta=1e-5
                actual=(model.evaluate(f(2.+delta))-model.evaluate(f(2.-delta)))/(2*delta)
                self.assertAlmostEqual(actual,target,delta=1e-6)

    def test_zero_slope_and_abs_kink_fail_closed(self):
        with self.assertRaises(UnresolvedAnchor):
            match_value_and_signed_slope('call',lambda _:1.,2.,target_value=0.,target_slope=.4)
        with self.assertRaises(UnresolvedAnchor):
            match_value_and_signed_slope('risk',lambda v:abs(v-2.)+.2*v,2.,target_value=0.,target_slope=.4)

    def test_not_a_clipped_probability_or_unbounded_calibration(self):
        with self.assertRaises(UnresolvedAnchor):
            match_value_and_signed_slope('margin',lambda v:1e-12*v,2.,target_value=1.,target_slope=.2)
        with self.assertRaises(UnresolvedAnchor):
            match_value_and_signed_slope('call',lambda v: v,2.,target_value=1.,target_slope=1e10)
        with self.assertRaises(UnresolvedAnchor):
            match_value_and_signed_slope('risk',lambda v: math.nan,2.,target_value=0.,target_slope=.1)

    def test_requires_positive_training_anchor_and_valid_channel(self):
        for channel,x in [('risk',0.),('other',2.),('call',math.inf)]:
            with self.subTest(channel=channel,x=x),self.assertRaises(UnresolvedAnchor):
                match_value_and_signed_slope(channel,math.log,x,target_value=.2,target_slope=.5)


if __name__=='__main__':
    unittest.main()
