"""P1 composition of alias and floating-point matched-slope refusal guards.

Finite probes reduce observed local matching errors; they cannot certify
arbitrary smoothness or a causal Call/Risk/Margin task-utility advantage.
"""
import math
import random
import unittest

from .matched_slope import match_local_slope, ordinary_sigmoid


class SlopeGuardCompositionTests(unittest.TestCase):
    def test_harmonic_alias_fails_third_incommensurate_stencil(self):
        h = 0.001
        z0 = 0.375
        ripple = lambda z: z + .01*math.sin(4*math.pi*(z-z0)/h)
        # Every original h and h/2 stencil node observes a nearly exact line;
        # the true derivative is 1+40*pi and must not be reported as 1.
        self.assertGreater(1+.04*math.pi/h, 100.)
        with self.assertRaisesRegex(ArithmeticError, 'Local derivative unstable'):
            match_local_slope(ripple, lambda z: z, anchor=z0, step=h)

    def test_large_offset_roundoff_still_denied(self):
        with self.assertRaisesRegex(ArithmeticError, 'roundoff|anchor'):
            match_local_slope(lambda z: 1e12+z, ordinary_sigmoid,
                              anchor=.125, step=.001)
        with self.assertRaisesRegex(ArithmeticError, 'anchor|roundoff'):
            match_local_slope(lambda z: 1e18+z, lambda z: .5+.25*z,
                              anchor=0., step=1e6)

    def test_hundred_smooth_signed_affine_channels_preserve_actual_anchor(self):
        rng = random.Random(202610311)
        for _ in range(100):
            a = rng.choice((-1, 1))*rng.uniform(.2, 2.)
            c = rng.uniform(-.8, .8)
            z0 = rng.uniform(-.6, .6)
            channel = lambda z: a*z+c
            ordinary = lambda z: ordinary_sigmoid(.7*z-.2)
            match = match_local_slope(channel, ordinary, anchor=z0, step=.001)
            self.assertLessEqual(abs(match.calibrated(channel(z0))-ordinary(z0)),1e-12)
            self.assertLessEqual(abs(match.scale*match.channel_slope-
                                     match.ordinary_slope),1e-10)
            self.assertEqual(math.copysign(1, match.scale), math.copysign(1, a))
            self.assertLess(match.roundoff_rel_floor, .005)

    def test_domain_and_kink_still_fail_closed(self):
        for channel in (lambda z: abs(z)+1,
                        lambda z: 1 if z >= 0 else -1):
            with self.assertRaises(ArithmeticError):
                match_local_slope(channel, ordinary_sigmoid, anchor=0.)


if __name__ == '__main__':
    unittest.main()
