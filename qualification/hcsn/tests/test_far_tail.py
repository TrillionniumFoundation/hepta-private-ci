"""Independent high-precision checks for the positive normal-tail difference."""

from dataclasses import fields
import unittest

import mpmath as mp
import torch

from .. import tensor as hx


def mp_log_pair(u, z, shifted, s):
    with mp.workdps(80):
        u, z, shifted, s = map(mp.mpf, (u, z, shifted, s))
        phi = lambda w: mp.erfc(-w/mp.sqrt(2))/2
        def integral(lam):
            if lam == 0:
                w = shifted*s
                return s*(mp.exp(-w*w/2)/mp.sqrt(2*mp.pi)+w*phi(w))
            return (phi(shifted*s)-mp.exp((lam*lam/2-lam*shifted)*s*s)*phi((shifted-lam)*s))/lam
        return float(mp.log(integral(u-z)-integral(u+z)))


class FarTailTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)

    def test_positive_pair_against_independent_80_digit_formula(self):
        cases = [(u, z, w/s, s) for u,z,s in ((.25,1.6,.045), (1.6,1.6,.045), (.4,1.4,.2))
                 for w in (-1.999, -2.001, -3.999, -4.001, -5.999, -6.001, -7.999, -8.001,
                           -9., -30., -268., -1000.)]
        for dtype, relative, absolute in ((torch.float64, 3e-14, 2e-11), (torch.float32, 3e-7, 2e-5)):
            for values in cases:
                theta = torch.tensor(values, dtype=dtype, requires_grad=True)
                actual = hx._log_normal_tail_pair(*theta)
                expected = mp_log_pair(*theta.detach().double().tolist())
                self.assertLessEqual(abs(float(actual.detach())-expected), absolute+relative*abs(expected))
                self.assertTrue(bool(torch.isfinite(torch.autograd.grad(actual, theta)[0]).all()))

    def test_tail_difference_parameter_gradient_matches_finite_difference(self):
        theta = torch.tensor([.4, 1.4, -45., .2], dtype=torch.float64, requires_grad=True)
        self.assertTrue(torch.autograd.gradcheck(lambda t: hx._log_normal_tail_pair(*t), (theta,),
                                                eps=1e-5, atol=3e-8, rtol=2e-6))

    def test_unused_rounded_pair_does_not_contaminate_backward(self):
        theta = torch.tensor([1e8, 1., -1e10, .2], dtype=torch.float32, requires_grad=True)
        value = hx._log_normal_tail_pair(*theta)
        gradient = torch.autograd.grad(value, theta)[0]
        self.assertTrue(bool(torch.isfinite(value) & torch.isfinite(gradient).all()))
        # The leading derivative of log Phi(shifted*s) is -shifted*s**2.
        torch.testing.assert_close(gradient[2], theta.new_tensor(4e8), atol=0, rtol=2e-6)
        torch.testing.assert_close(gradient[3], theta.new_tensor(-2e19), atol=0, rtol=2e-6)

    def test_original_fp32_failure_has_finite_full_equity_gradients(self):
        names = tuple(f.name for f in fields(hx.HXParams))
        results = {}
        for dtype in (torch.float64, torch.float32):
            for prepared in (False, True):
                theta = torch.tensor([.05,.02,.2,5.,100.,.05,.25,.6,.01], dtype=dtype, requires_grad=True)
                x = torch.tensor(12., dtype=dtype, requires_grad=True)
                params = hx.HXParams(**dict(zip(names, theta)))
                value = (hx.prepared_hx_equity(x, hx.prepare_hx_equity(params)) if prepared else hx.hx_equity(x, params))
                gradients = torch.autograd.grad(value, (theta,x))
                self.assertTrue(all(bool(torch.isfinite(t).all()) for t in (value,*gradients)))
                results[dtype,prepared] = (value.detach().double(), *(t.double() for t in gradients))
        reference = results[torch.float64,False]
        for (dtype, prepared), values in results.items():
            for actual, expected in zip(values, reference):
                torch.testing.assert_close(actual, expected, atol=2e-4, rtol=8e-5)


if __name__ == '__main__':
    unittest.main()
