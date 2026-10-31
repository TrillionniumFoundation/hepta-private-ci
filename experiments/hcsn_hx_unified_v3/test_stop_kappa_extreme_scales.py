"""Independent 320-digit kappa/renewal regression for resolvable extreme scales.

Research-only. Does not certify a full parameter domain, binary64 intervals,
HX coupled obstacles, or bounded Jacobians as h approaches zero.
"""
from decimal import Decimal, localcontext
import math
import unittest

from .stopping import Stop, regenerative_boundary


def decimal_boundary(p: Stop) -> tuple[float, float]:
    """Derive kappa and the renewal root from the original float inputs."""
    with localcontext() as ctx:
        ctx.prec = 320
        d = Decimal.from_float
        mu, sigma, rho = d(p.drift), d(p.diffusion), d(p.discount)
        root = (mu * mu + 2 * rho * sigma * sigma).sqrt()
        # Avoid the positive-drift cancellation of root-mu even at 320 dps.
        k = 2 * rho / (root + mu) if mu >= 0 else (root - mu) / (sigma * sigma)
        h = k * (d(p.cost) - d(p.reset)) + rho * d(p.refractory)
        if not h > 0:
            raise AssertionError('invalid independent renewal exponent')
        t = (2 * h).sqrt() if h < Decimal('.2') else 1 - (-h - 1).exp()
        for _ in range(70):
            if t < Decimal('.01'):
                term = t * t
                residual = term / 2
                for n in range(3, 40):
                    term *= t
                    residual += term / n
                residual -= h
            else:
                residual = -(1 - t).ln() - t - h
            delta = residual * (1 - t) / t
            t -= delta
            if abs(delta) <= abs(t) * Decimal('1e-270'):
                break
        if not 0 < t < 1:
            raise AssertionError('independent renewal root outside (0,1)')
        return float(k), float(d(p.cost) + t / k)


class ExtremeScaleKappaTests(unittest.TestCase):
    def test_finite_kappa_survives_intermediate_float_overflow_and_underflow(self):
        cases = (
            Stop(1e308, 1., 1e308, 0., -.1, 0.),
            Stop(1e308, 1., 1., 0., -.1, 0.),
            Stop(1e154, 1., 1e308, 0., -1e-155, 0.),
            Stop(-1e308, 1e155, 1., 0., -1., 0.),
            Stop(0., 1e308, 1e308, 0., -1e154, 0.),
            Stop(0., 1e-320, 1e-320, 0., -1e-160, 0.),
        )
        for p in cases:
            expected_k, expected_b = decimal_boundary(p)
            with self.subTest(drift=p.drift, sigma=p.diffusion, rho=p.discount):
                k = p.kappa
                b = regenerative_boundary(p)
                self.assertTrue(math.isfinite(k) and k > 0)
                self.assertTrue(math.isfinite(b) and b > p.cost)
                self.assertLessEqual(abs(k / expected_k - 1), 4e-14)
                self.assertLessEqual(abs(b / expected_b - 1), 4e-14)


if __name__ == '__main__':
    unittest.main()
