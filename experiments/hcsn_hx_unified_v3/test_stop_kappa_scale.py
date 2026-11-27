"""P0 dimensional-root overflow/underflow adversarial tests, research only.

Decimal is an independent high-precision positive root of the quadratic;
these tests do not certify HX finance, coupled QVI, FP32, or a neural model.
"""
from dataclasses import replace
from decimal import Decimal, localcontext
import math
import random
import unittest

from .stopping import Stop, one_shot_boundary, regenerative_boundary


def decimal_kappa(p: Stop) -> Decimal:
    """The positive quadratic root with exact f64 input coefficients."""
    with localcontext() as ctx:
        ctx.prec = 180
        mu, sigma, rho = (Decimal.from_float(p.drift),
                          Decimal.from_float(p.diffusion),
                          Decimal.from_float(p.discount))
        scale = (mu*mu + 2*rho*sigma*sigma).sqrt()
        # Rationalize only the oracle's positive-drift branch; never reuse
        # the candidate implementation's dimensionless evaluation.
        return 2*rho/(scale+mu) if mu >= 0 else (scale-mu)/(sigma*sigma)


class StoppingKappaScaleTests(unittest.TestCase):
    def assert_reference(self, p: Stop, *, rel: float = 5e-13):
        reference = decimal_kappa(p)
        actual = p.kappa
        self.assertTrue(math.isfinite(actual) and actual > 0)
        relative = abs(Decimal.from_float(actual)-reference)/reference
        self.assertLess(float(relative), rel, (p, actual, str(reference)))

    def test_negative_drift_sigma_square_overflow_is_repaired(self):
        cases = (Stop(-1., 1e200, .1, 0., -1., 0.),
                 Stop(-1e308, 1e308, .1, 0., -1., 0.),
                 Stop(-1e308, 1e307, .1, 0., -1., 0.))
        for p in cases:
            with self.subTest(p=p):
                self.assert_reference(p)
        # The very large-volatility scalar boundary remains representable.
        p = cases[0]
        b = regenerative_boundary(p)
        self.assertTrue(math.isfinite(b) and p.cost < b < one_shot_boundary(p))

    def test_positive_drift_denominator_overflow_does_not_erase_root(self):
        cases = (Stop(1e308, 1e308, .1, 0., -1., 0.),
                 Stop(1e308, 1e-200, .1, 0., -1., 0.))
        for p in cases:
            with self.subTest(p=p):
                self.assert_reference(p, rel=1e-8)

    def test_double_discount_and_large_scale_remain_finite(self):
        for p in (Stop(0., 1., 1e308, 0., -1., 0.),
                  Stop(0., 1e308, 1e308, 0., -1., 0.),
                  Stop(1e308, 1e-200, 1e308, 0., -1., 0.),
                  Stop(-1e308, 1e308, 1e308, 0., -1., 0.)):
            with self.subTest(p=p):
                self.assert_reference(p)

    def test_resolved_renewal_boundary_and_diffusion_sensitivity(self):
        p = Stop(-1., 1e200, .1, 0., -1., 0.)
        b = regenerative_boundary(p)
        self.assertAlmostEqual(b/math.sqrt(2/p.kappa), 1., delta=2e-12)
        eps = 1e-5
        kp = replace(p, diffusion=p.diffusion*(1+eps)).kappa
        km = replace(p, diffusion=p.diffusion*(1-eps)).kappa
        elasticity = (kp-km)/(2*eps*p.kappa)
        self.assertAlmostEqual(elasticity, -1., delta=2e-9)

    def test_unresolved_subnormal_or_unrepresentable_roots_refuse(self):
        for p in (Stop(1e308, 1e308, 1e-10, 0., -1., 0.),
                  Stop(-1e308, 1e-308, .1, 0., -1., 0.),
                  Stop(0., 1e-300, 1e308, 0., -1., 0.)):
            with self.subTest(p=p), self.assertRaises(ArithmeticError):
                _ = p.kappa

    def test_seeded_extreme_parameter_sweep_against_decimal(self):
        rng = random.Random(2026103106)
        accepted = refused = 0
        for index in range(1024):
            sigma = 10**rng.uniform(-300, 300)
            rho = 10**rng.uniform(-290, 300)
            mu = (0. if index % 17 == 0 else
                  (-1. if index % 2 else 1.)*10**rng.uniform(-300, 300))
            p = Stop(mu, sigma, rho, 0., -1., 0.)
            reference = decimal_kappa(p)
            try:
                actual = p.kappa
            except ArithmeticError:
                refused += 1
                # Refusal is allowed only when the rounded true value is
                # non-finite, zero, or has >1e-9 binary64 relative ULP.
                rounded = float(reference)
                if math.isfinite(rounded) and rounded > 0:
                    self.assertGreater(math.ulp(rounded)/rounded, 1e-9,
                                       (index, p, str(reference)))
                continue
            accepted += 1
            relative = abs(Decimal.from_float(actual)-reference)/reference
            self.assertLess(float(relative), 1e-9, (index, p, actual))
        self.assertGreater(accepted, 700)
        self.assertGreater(refused, 50)


if __name__ == '__main__':
    unittest.main()
