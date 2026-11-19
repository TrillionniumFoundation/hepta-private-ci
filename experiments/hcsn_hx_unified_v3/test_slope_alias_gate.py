"""Research P1: prevent a shared h / (h/2) sampling-grid alias.

An irrational-ratio probe reduces one demonstrated blind spot; finite
stencils do not prove global regularity or causal mechanism superiority.
"""
import math
import unittest

from .matched_slope import match_local_slope, ordinary_sigmoid


class SlopeAliasGateTests(unittest.TestCase):
    def test_harmonic_alias_false_match_is_refused(self):
        h = .001
        anchor = .375
        ripple = lambda z: z + .01 * math.sin(4 * math.pi * (z-anchor)/h)
        # At x=anchor+n*h/2, sin(2*pi*n)=0. Parent's h and h/2
        # stencils observe an exact line with slope ~1; true derivative
        # at the anchor is 1 + 40*pi =~ 126.664.
        true_derivative = 1 + .04*math.pi/h
        self.assertGreater(true_derivative, 100)
        with self.assertRaisesRegex(ArithmeticError, 'Local derivative unstable'):
            match_local_slope(ripple, lambda z: z, anchor=anchor, step=h)

    def test_smooth_positive_negative_slopes_still_match(self):
        controls = (
            (lambda z: math.exp(.4*z), lambda z: ordinary_sigmoid(.7*z-.2)),
            (lambda z: math.exp(-.4*z), ordinary_sigmoid),
            (lambda z: z*z+1, lambda z: -2*z+4),
        )
        for fn, ctrl in controls:
            with self.subTest(fn=fn):
                m = match_local_slope(fn, ctrl, anchor=.55, step=.001)
                self.assertLess(m.stencil_rel_disagreement,1e-5)
                self.assertLess(abs(m.calibrated(fn(.55))-ctrl(.55)),1e-10)
                self.assertLess(abs(m.scale*m.channel_slope-m.ordinary_slope),1e-10)

    def test_three_scale_probe_still_rejects_kink(self):
        with self.assertRaises(ArithmeticError):
            match_local_slope(lambda z: abs(z)+1, ordinary_sigmoid,anchor=0.)


if __name__ == '__main__':
    unittest.main()
