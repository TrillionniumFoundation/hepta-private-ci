"""Independent integral and differentiation checks for the tensor kernels."""

import math
import unittest

import numpy as np
from scipy.integrate import quad

try:
    import torch
except ModuleNotFoundError:
    torch = None

if torch is not None:
    from hcsn import tensor as hx


@unittest.skipIf(torch is None, "PyTorch is required; the CI job treats its absence as a failure")
class PassageTensorTests(unittest.TestCase):
    def test_integrals_float64_and_float32(self):
        for dtype, tolerance in [(torch.float64, 2e-11), (torch.float32, 3e-6)]:
            for mu in [-0.3, 0.0, 0.2]:
                for x in [0.001, 0.05, 0.4, 2.0]:
                    xx = torch.tensor(x, dtype=dtype)
                    for time in [0.05, 1.0, 4.0]:
                        pdf = lambda t: x / (0.3 * math.sqrt(2 * math.pi * t**3)) * math.exp(-(x + mu*t)**2 / (2 * 0.3**2 * t))
                        # Splitting at the approximate first-passage scale makes
                        # quadrature resolve the narrow peak when x is tiny.
                        points = sorted({0.0, min(time, x*x/0.3**2), time})
                        for q in [0.0, 0.07]:
                            expected = sum(quad(lambda t: math.exp(-q*t) * pdf(t), lo, hi, epsabs=2e-12)[0] for lo, hi in zip(points, points[1:]))
                            actual = hx.discounted_first_passage(xx, time, mu, 0.3, q).item()
                            self.assertAlmostEqual(actual, expected, delta=tolerance)
                        self.assertAlmostEqual(hx.first_passage_cdf(xx,time,mu,0.3).item(), hx.discounted_first_passage(xx,time,mu,0.3,0.0).item(), delta=tolerance)

    def test_autograd_matches_finite_differences(self):
        args = tuple(torch.tensor(v, dtype=torch.float64, requires_grad=True) for v in [0.22, 0.7, -0.03, 0.31, 0.04])
        self.assertTrue(torch.autograd.gradcheck(hx.discounted_first_passage, args, eps=1e-6, atol=2e-7, rtol=2e-5))
        self.assertTrue(torch.autograd.gradcheck(hx.first_passage_cdf, args[:4], eps=1e-6, atol=2e-7, rtol=2e-5))
        x, t, mu, sigma, _ = args
        self.assertTrue(torch.autograd.gradcheck(hx.first_passage_density, (t,x,mu,sigma), eps=1e-6, atol=2e-7, rtol=2e-5))

    def test_zero_discount_zero_drift_has_correct_gradient(self):
        q = torch.tensor(0.0, dtype=torch.float64, requires_grad=True)
        mu = torch.tensor(0.0, dtype=torch.float64, requires_grad=True)
        x, time, sigma = 0.2, 0.8, 0.3
        value = hx.discounted_first_passage(x,time,mu,sigma,q)
        dq, dm = torch.autograd.grad(value,(q,mu))
        pdf = lambda t: x/(sigma*math.sqrt(2*math.pi*t**3))*math.exp(-x*x/(2*sigma*sigma*t))
        expected = -quad(lambda t:t*pdf(t),0,time,epsabs=1e-13)[0]
        self.assertAlmostEqual(dq.item(),expected,delta=1e-12)
        self.assertAlmostEqual(dm.item(), -x/sigma**2 * value.item(),delta=1e-12)

    def test_cdf_time_derivative_is_density(self):
        for dtype,tol in [(torch.float64,2e-12),(torch.float32,2e-6)]:
            time = torch.tensor([0.1,0.5,2.0],dtype=dtype,requires_grad=True)
            value = hx.first_passage_cdf(0.2,time,-0.04,0.3)
            derivative = torch.autograd.grad(value.sum(),time)[0]
            density = hx.first_passage_density(time,0.2,-0.04,0.3)
            torch.testing.assert_close(derivative,density,atol=tol,rtol=tol)

    def test_boundary_atom_and_surviving_t0(self):
        x = torch.tensor([0.0,0.2],dtype=torch.float64)
        expected = torch.tensor([1.0,0.0],dtype=torch.float64)
        torch.testing.assert_close(hx.first_passage_cdf(x,0.0,0.1,0.2),expected)
        torch.testing.assert_close(hx.discounted_first_passage(x,0.0,0.1,0.2,0.05),expected)
        torch.testing.assert_close(hx.first_passage_density(0.0,x,0.1,0.2),torch.zeros_like(x))
        # At a positive horizon, keep the nonzero right derivative at x=0.
        zero = torch.tensor(0.0,dtype=torch.float64,requires_grad=True)
        value = hx.first_passage_cdf(zero,1.0,0.0,0.3)
        slope = torch.autograd.grad(value,zero)[0]
        self.assertAlmostEqual(slope.item(),-math.sqrt(2/math.pi)/0.3,delta=1e-12)

    def test_small_margin_no_rollover_and_tails(self):
        for dtype,tol in [(torch.float64,1e-12),(torch.float32,5e-6)]:
            x = torch.tensor([0.0,1e-7,1e-4,0.5,4.0],dtype=dtype,requires_grad=True)
            ratio = hx.simple_equity_ratio(x,2.2)
            self.assertTrue(bool((ratio>=0).all()))
            self.assertTrue(bool(torch.isfinite(torch.autograd.grad(ratio.sum(),x)[0]).all()))
            self.assertAlmostEqual(ratio[1].item()/1e-14,1.6,delta=tol+1e-6)
            for mu in [-1.0,0.0,1.0]:
                f = hx.first_passage_cdf(x,0.001,mu,0.1)
                g = hx.discounted_first_passage(x,0.001,mu,0.1,0.03)
                self.assertTrue(bool(torch.isfinite(f+g).all()))
                self.assertTrue(bool((g<=f+tol).all()))
                self.assertTrue(bool((f<=1+tol).all()))

    def test_invalid_domains_are_rejected(self):
        for args in [(-0.1,1,0,0.3),(0.1,-1,0,0.3),(0.1,1,0,0),(0.1,1,float("nan"),0.3)]:
            with self.assertRaises(ValueError):
                hx.first_passage_cdf(*args)
        with self.assertRaises(ValueError):
            hx.discounted_first_passage(0.1,1,0,0.3,-0.01)


if __name__ == "__main__":
    unittest.main()
