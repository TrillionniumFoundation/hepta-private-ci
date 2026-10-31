"""P2 fail-closed first-event CDF precision checks for two-state CTMC.

A numerically erased event CDF increment must not be accepted as evidence
of zero first-event probability. These are bounded f64 source checks, not
full HCSN learning/physics proofs or complete-repository CI receipts.
"""

from decimal import Decimal, localcontext
import math
import unittest

from .renewal_event_oracle import RenewalState, advance


class FirstEventCdfPrecisionTests(unittest.TestCase):
    def test_positive_first_fire_increment_cannot_disappear_at_high_cdf(self):
        prefix = advance(RenewalState.initial(1.), 1., 1., 30.)
        self.assertLess(prefix.ever_fired, 1.)
        self.assertGreater(prefix.no_fire_active, 0.)
        # Exact killed mass is exp(-30). Over dt=1e-4 first hits have
        # nonzero probability exp(-30)*(1-exp(-1e-4)) ~ 9.36e-18, far
        # below the binary64 ULP of the nearly unit accumulated CDF.
        with localcontext() as ctx:
            ctx.prec = 100
            a = Decimal.from_float(30.)
            dt = Decimal.from_float(1e-4)
            delta = (-a).exp() * (1 - (-dt).exp())
        self.assertGreater(delta, Decimal(0))
        self.assertLess(float(delta), math.ulp(prefix.ever_fired) / 2.)
        with self.assertRaisesRegex(ArithmeticError, 'first-fire CDF increment erased'):
            advance(prefix, 1., 1., 1e-4)

    def test_near_saturation_requires_explicit_refusal(self):
        prefix = advance(RenewalState.initial(1.), 1., 1., 35.)
        self.assertGreater(prefix.no_fire_active, 0.)
        with self.assertRaises(ArithmeticError):
            advance(prefix, 1., 1., 1e-4)

    def test_normal_resolvable_first_fire_probabilities_remain_monotone(self):
        prefix = advance(RenewalState.initial(1.), 1., 1., 20.)
        suffix = advance(prefix, 1., 1., .01)
        self.assertGreater(suffix.ever_fired, prefix.ever_fired)
        self.assertGreater(suffix.expected_count, prefix.expected_count)
        self.assertGreater(suffix.time, prefix.time)

    def test_initial_refractory_has_real_first_fire_and_repeated_count(self):
        final = advance(RenewalState.initial(0.), 2., 3., .2)
        self.assertTrue(0. < final.ever_fired < 1.)
        self.assertGreater(final.expected_count, final.ever_fired)

    def test_zero_duration_is_identity(self):
        state = advance(RenewalState.initial(.4), 2., 3., .2)
        self.assertEqual(advance(state, 2., 3., 0.), state)


if __name__ == '__main__':
    unittest.main()
