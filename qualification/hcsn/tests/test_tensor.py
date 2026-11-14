"""Independent integral and differentiation checks for the tensor kernels."""

import math
import unittest

import numpy as np
from scipy.integrate import quad
from scipy.special import ndtr

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

    def test_zero_discount_zero_drift_second_derivatives(self):
        """Truncated first-passage moments independently determine the Taylor coefficients."""
        x, time, sigma = 0.2, 0.8, 0.3
        pdf = lambda t: x/(sigma*math.sqrt(2*math.pi*t**3))*math.exp(-x*x/(2*sigma*sigma*t))
        probability = quad(pdf, 0, time, epsabs=1e-13)[0]
        moment1 = quad(lambda t: t*pdf(t), 0, time, epsabs=1e-13)[0]
        moment2 = quad(lambda t: t*t*pdf(t), 0, time, epsabs=1e-13)[0]
        a = x/sigma**2
        for dtype, tolerance in [(torch.float64, 2e-11), (torch.float32, 2e-5)]:
            q = torch.tensor(0.0, dtype=dtype, requires_grad=True)
            mu = torch.tensor(0.0, dtype=dtype, requires_grad=True)
            value = hx.discounted_first_passage(x, time, mu, sigma, q)
            dq, dm = torch.autograd.grad(value, (q, mu), create_graph=True)
            dqq = torch.autograd.grad(dq, q, retain_graph=True)[0]
            dqm = torch.autograd.grad(dq, mu, retain_graph=True)[0]
            dmm = torch.autograd.grad(dm, mu)[0]
            expected = (moment2, a*moment1, a*a*probability-moment1/sigma**2)
            for actual, target in zip((dqq, dqm, dmm), expected):
                self.assertTrue(bool(torch.isfinite(actual)))
                self.assertAlmostEqual(actual.item(), target, delta=tolerance*(1+abs(target)))

    def test_discount_taylor_switch_keeps_value_and_gradient(self):
        """The near/regular switch must agree with an integral on both sides."""
        x, time, sigma = 0.2, 0.8, 0.3
        a, beta = x/sigma**2, math.sqrt(time)/sigma
        # This probes the chi-based cutoff documented by the implementation.
        q_switch = 1e-6/(2*sigma**2*(a+beta)**2)
        pdf = lambda t: x/(sigma*math.sqrt(2*math.pi*t**3))*math.exp(-x*x/(2*sigma*sigma*t))
        for dtype, value_tol, slope_tol in [(torch.float64, 2e-12, 2e-8),
                                             (torch.float32, 3e-6, 1e-3)]:
            for factor in (0.5, 0.99, 1.01, 2.0):
                q_value = factor*q_switch
                q = torch.tensor(q_value, dtype=dtype, requires_grad=True)
                actual = hx.discounted_first_passage(x, time, 0.0, sigma, q)
                slope = torch.autograd.grad(actual, q)[0]
                expected = quad(lambda t: math.exp(-q_value*t)*pdf(t),0,time,epsabs=1e-13)[0]
                expected_slope = -quad(lambda t: t*math.exp(-q_value*t)*pdf(t),0,time,epsabs=1e-13)[0]
                self.assertAlmostEqual(actual.item(),expected,delta=value_tol)
                self.assertAlmostEqual(slope.item(),expected_slope,delta=slope_tol)

    def test_fp32_gradients_against_differentiated_density_integrals(self):
        """An independent integral checks every G input without finite-difference noise."""
        for x, time, mu, sigma, q in [(0.05,0.3,-0.2,0.2,0.07),
                                     (0.2,0.8,0.0,0.3,0.0),
                                     (0.4,1.1,0.2,0.5,0.04)]:
            values = tuple(torch.tensor(v,dtype=torch.float32,requires_grad=True)
                           for v in (x,time,mu,sigma,q))
            actual = hx.discounted_first_passage(*values)
            gradients = torch.autograd.grad(actual,values)

            def pdf(t):
                return x/(sigma*math.sqrt(2*math.pi*t**3))*math.exp(-(x+mu*t)**2/(2*sigma**2*t))

            def expectation(multiplier):
                return quad(lambda t: math.exp(-q*t)*pdf(t)*multiplier(t),
                            0,time,epsabs=1e-12,epsrel=1e-11)[0]

            expected = (
                expectation(lambda t: 1/x-(x+mu*t)/(sigma**2*t)),
                math.exp(-q*time)*pdf(time),
                expectation(lambda t: -(x+mu*t)/sigma**2),
                expectation(lambda t: -1/sigma+(x+mu*t)**2/(sigma**3*t)),
                expectation(lambda t: -t),
            )
            for actual_gradient, target in zip(gradients,expected):
                self.assertTrue(bool(torch.isfinite(actual_gradient)))
                self.assertAlmostEqual(actual_gradient.item(),target,delta=4e-5*(1+abs(target)))

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

    def test_positive_time_boundary_right_derivatives(self):
        """At t>0 the regular density has a nonzero right derivative at x=0 too."""
        time, sigma = 0.7, 0.3
        scale = sigma*math.sqrt(time)
        phi = lambda z: math.exp(-z*z/2)/math.sqrt(2*math.pi)
        for dtype, tolerance in [(torch.float64,2e-11),(torch.float32,2e-5)]:
            for mu in (-0.2,0.0,0.2):
                for q in (0.0,0.05):
                    x = torch.tensor(0.0,dtype=dtype,requires_grad=True)
                    f = hx.first_passage_cdf(x,time,mu,sigma)
                    g = hx.discounted_first_passage(x,time,mu,sigma,q)
                    density = hx.first_passage_density(time,x,mu,sigma)
                    slopes = [torch.autograd.grad(value,x,retain_graph=True)[0]
                              for value in (f,g,density)]
                    chi = math.sqrt(mu*mu+2*q*sigma*sigma)
                    v = chi*math.sqrt(time)/sigma
                    expected = (
                        -2*phi(mu*math.sqrt(time)/sigma)/scale
                        -2*mu/sigma**2*ndtr(mu*math.sqrt(time)/sigma),
                        -2*phi(v)/scale-(mu+chi*(2*ndtr(v)-1))/sigma**2,
                        math.exp(-mu*mu*time/(2*sigma*sigma))/(sigma*math.sqrt(2*math.pi*time**3)),
                    )
                    for value, target in zip(slopes,expected):
                        self.assertTrue(bool(torch.isfinite(value)))
                        self.assertAlmostEqual(value.item(),target,delta=tolerance*(1+abs(target)))

    def test_t0_mask_does_not_propagate_nan_gradients(self):
        """At the discontinuous corner only finite implementation gradients are asserted."""
        for dtype in (torch.float64,torch.float32):
            x = torch.tensor([0.0,0.02,2.0],dtype=dtype,requires_grad=True)
            time = torch.zeros(3,dtype=dtype,requires_grad=True)
            mu = torch.tensor([-0.1,0.0,0.2],dtype=dtype,requires_grad=True)
            sigma = torch.tensor(0.3,dtype=dtype,requires_grad=True)
            q = torch.tensor([0.0,0.0,0.07],dtype=dtype,requires_grad=True)
            f = hx.first_passage_cdf(x,time,mu,sigma)
            g = hx.discounted_first_passage(x,time,mu,sigma,q)
            density = hx.first_passage_density(time,x,mu,sigma)
            expected = torch.tensor([1.0,0.0,0.0],dtype=dtype)
            torch.testing.assert_close(f,expected,rtol=0,atol=0)
            torch.testing.assert_close(g,expected,rtol=0,atol=0)
            torch.testing.assert_close(density,torch.zeros_like(density),rtol=0,atol=0)
            for gradient in torch.autograd.grad((f+g+density).sum(),(x,time,mu,sigma,q)):
                self.assertTrue(bool(torch.isfinite(gradient).all()))

    def test_time_unit_rescaling(self):
        for dtype,tolerance in [(torch.float64,2e-12),(torch.float32,4e-6)]:
            x = torch.tensor([0.01,0.2,0.9],dtype=dtype)
            time,mu,sigma,q=0.7,-0.03,0.3,0.05
            for scale in (0.1,10.0):
                f0=hx.first_passage_cdf(x,time,mu,sigma)
                f1=hx.first_passage_cdf(x,time*scale,mu/scale,sigma/math.sqrt(scale))
                g0=hx.discounted_first_passage(x,time,mu,sigma,q)
                g1=hx.discounted_first_passage(x,time*scale,mu/scale,sigma/math.sqrt(scale),q/scale)
                d0=hx.first_passage_density(time,x,mu,sigma)
                d1=hx.first_passage_density(time*scale,x,mu/scale,sigma/math.sqrt(scale))
                for first,second in ((f0,f1),(g0,g1),(d0,scale*d1)):
                    torch.testing.assert_close(first,second,atol=tolerance,rtol=tolerance)

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
