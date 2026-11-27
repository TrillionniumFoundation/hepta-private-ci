"""Research-only refusal of impossible f64 probabilities in opt-in coupons.

The frozen witness was independently checked using a 100-dps Brownian
first-passage reflection expression. Its true F is strictly below one
(1-F is approximately 7.24405709652604e-58), while the unmodified parent
quadrature returns F=1.0000000000000004. This is a refusal guard, NOT a
rigorous quadrature interval certification or production authorization.
"""
import unittest

from .bond_fpt_independent import integrate_passage


class DirectProbabilityOrderTests(unittest.TestCase):
    _WITNESS = dict(
        x=0.8355996106828565,
        drift=-0.035150530007594404,
        sigma=0.044933202022388846,
        discount=1.1123783467156558e-05,
        horizon=456.6680322724879,
    )

    def test_opt_in_rejects_unresolved_probability_exceeding_one(self):
        with self.assertRaisesRegex(ArithmeticError, 'Direct first-passage probability ordering unresolved'):
            integrate_passage(**self._WITNESS, compute_default_duration=True)

    def test_opt_in_rejects_unresolved_discounted_probability_inversion(self):
        # Independent 110-dps reflection: true F-G = 1.9998118040413e-17.
        # Parent f64 quadrature instead reports G-F = one positive ULP.
        kw=dict(x=0.0008205334528763317,
                drift=0.07599208604968195,
                sigma=0.19547770416678287,
                discount=5.555215349483322e-14,
                horizon=0.012741858595454054)
        with self.assertRaisesRegex(ArithmeticError, 'Direct first-passage probability ordering unresolved'):
            integrate_passage(**kw, compute_default_duration=True)

    def test_non_opt_in_preserves_frozen_reference_output(self):
        # Preserve historical observations; do not silently clamp to one.
        passage=integrate_passage(**self._WITNESS)
        self.assertGreater(passage.probability, 1.)
        self.assertIsNone(passage.default_coupon_duration)

    def test_ordinary_opt_in_result_remains_available(self):
        passage=integrate_passage(.7, drift=.01, sigma=.22,
                                  discount=.09, horizon=3.,
                                  compute_default_duration=True)
        self.assertTrue(0. <= passage.discounted <= passage.probability <= 1.)
        self.assertIsNotNone(passage.default_coupon_duration)


if __name__ == '__main__':
    unittest.main()
