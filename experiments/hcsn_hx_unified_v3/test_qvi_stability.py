"""Research-only source-exact P0 QVI cancellation and overflow negative controls.

The one-dimensional continuation branch is an exponential solution of its
homogeneous diffusion ODE; the obstacle must retain its strictly negative
signed value despite huge but finite continuation values. These tests do NOT
certify arbitrary parameters, coupled HX obstacles or low-precision kernels.
"""
import math
import unittest
from decimal import Decimal, localcontext

from .stopping import Stop, qvi, regenerative_boundary, regenerative_value


class QVINumericalStabilityTests(unittest.TestCase):
    def test_extreme_diffusion_far_continuation_is_finite_and_negative(self):
        # Parent #4428: sigma**2 overflows, despite finite state/value and
        # genuine negative obstacle at x well below the firing boundary.
        p = Stop(-1.0, 1e200, .1, 0.0, -1.0, 0.0)
        b = regenerative_boundary(p)
        x = -1e200
        result = qvi(p, x)
        self.assertFalse(result['fire'])
        self.assertTrue(math.isfinite(result['value']))
        self.assertEqual(result['generator'], 0.0)
        self.assertLess(result['obstacle'], -1e198)
        self.assertEqual(result['complementarity'], 0.0)
        # Independent 240-digit decimal evaluation of the *rounded supplied*
        # boundary, without use of the implementation's expm1 factoring.
        with localcontext() as ctx:
            ctx.prec = 240
            D = lambda n: Decimal(str(n))
            mu, sigma, rho = D(p.drift), D(p.diffusion), D(p.discount)
            kk = ((mu*mu + 2*rho*sigma*sigma).sqrt()-mu)/(sigma*sigma)
            bb, xx, rr = D(b), D(x), D(p.reset)
            amp = (bb-D(p.cost))/(1-(-rho*D(p.refractory)-kk*(bb-rr)).exp())
            v = amp*(kk*(xx-bb)).exp()
            reset_value = amp*(kk*(rr-bb)).exp()
            oracle = xx-D(p.cost)+(-rho*D(p.refractory)).exp()*reset_value-v
            self.assertLess(float(abs(D(result['obstacle'])-oracle)/abs(oracle)),1e-12)

    def test_extreme_near_boundary_refuses_unresolved_sign(self):
        p = Stop(-1.0, 1e200, .1, 0.0, -1.0, 0.0)
        b = regenerative_boundary(p)
        for x in (b/2, b*.9, 0.):
            with self.subTest(x=x), self.assertRaisesRegex(
                ArithmeticError, 'obstacle sign unresolved'):
                qvi(p,x)

    def test_finite_nominal_qvi_continuation_and_fire(self):
        p = Stop(.02, .2, .1, .5, 0.0, .1)
        b = regenerative_boundary(p)
        for x in (p.reset, p.cost, b/2, b-1e-8, b, b+.2):
            with self.subTest(x=x):
                result = qvi(p, x)
                self.assertLessEqual(result['obstacle'], 1e-10)
                self.assertLessEqual(result['generator'], 1e-10)
                self.assertAlmostEqual(result['complementarity'], 0.0, delta=1e-10)
                self.assertEqual(result['fire'], x>=b)

    def test_explicit_suboptimal_threshold_retains_true_obstacle_sign(self):
        p = Stop(.02, .2, .1, .5, 0.0, .1)
        b = regenerative_boundary(p) * 1.15
        x = .65
        got = qvi(p, x, boundary=b)
        v = regenerative_value(p, x, boundary=b)
        r = regenerative_value(p, p.reset, boundary=b)
        direct = (x-p.cost) + p.delay_discount*r-v
        self.assertAlmostEqual(got['obstacle'], direct, delta=1e-11)
        self.assertEqual(got['generator'], 0.0)

    def test_unrepresentable_value_is_refused_not_reported_as_qvi(self):
        p = Stop(1e308, 1e308, .1, 0.0, -1.0, 0.0)
        with self.assertRaises(ArithmeticError):
            qvi(p, -.5)


if __name__ == '__main__':
    unittest.main()
