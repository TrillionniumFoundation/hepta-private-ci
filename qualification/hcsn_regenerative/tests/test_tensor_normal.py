"""First-order normal-tail regression, including real post-release failures."""

import math
import unittest

from scipy.special import erfcx
import torch

from qualification.hcsn_regenerative.audit import five_point_derivative
from qualification.hcsn_regenerative.tensor import TensorDiffusion, TensorReset, finite_horizon_value
from qualification.hcsn_regenerative.tensor_normal import log_normal_cdf
from qualification.hcsn_regenerative.tests.test_short_tensor import (
    DEVICES, DTYPES, inputs, positive_occupation,
)


def occupation_oracle(values, margin, refractory):
    x, horizon, mu, sigma, q = values
    result = positive_occupation(*values)
    for n in range(1, int(math.floor(horizon/refractory))+2):
        remaining = horizon-n*refractory
        if remaining <= 0:
            continue
        distance = x+(n-1)*margin
        result += math.exp(-q*n*refractory)*(
            positive_occupation(distance+margin, remaining, mu, sigma, q)
            -positive_occupation(distance, remaining, mu, sigma, q))
    return result


class NormalTailGradientTests(unittest.TestCase):
    def test_forward_is_unchanged_and_tail_first_derivative_is_finite(self):
        for device in DEVICES:
            for dtype in DTYPES:
                z = torch.tensor([-1e7, -1e3, -30., -1., 0., 1., 8.],
                                 dtype=dtype, device=device, requires_grad=True)
                result = log_normal_cdf(z)
                self.assertTrue(torch.equal(result.detach(), torch.special.log_ndtr(z).detach()))
                derivative = torch.autograd.grad(result.sum(), z)[0]
                self.assertTrue(bool(torch.isfinite(derivative).all()))
                for score, observed in zip(z.detach().cpu().tolist(), derivative.cpu().tolist()):
                    expected = (math.sqrt(2/math.pi)/erfcx(-score/math.sqrt(2)) if score <= 0
                                else math.exp(-.5*score*score)/math.sqrt(2*math.pi)
                                /(0.5*math.erfc(-score/math.sqrt(2))))
                    self.assertLessEqual(abs(observed-expected),
                                         (3e-6 if dtype == torch.float32 else 1e-12)*abs(expected)+1e-300)
                far = torch.tensor([-1e7, -1e3], dtype=dtype, device=device, requires_grad=True)
                zero = torch.autograd.grad(log_normal_cdf(far).exp().sum(), far)[0]
                self.assertTrue(bool(torch.isfinite(zero).all()))
                self.assertEqual(zero.cpu().tolist(), [0., 0.])

    def test_regular_release_all_gradients_and_independent_x_gradient(self):
        for device in DEVICES:
            for dtype in DTYPES:
                z = inputs((1e-5, 2.1e-6, -.1, .3, .15), dtype, device, True)
                actual = finite_horizon_value(TensorDiffusion(*z[2:]), TensorReset(.25, 1e-6, 0.),
                                               *z[:2], active_reward=1.)
                gradients = torch.autograd.grad(actual.active_time, z)
                self.assertTrue(all(bool(torch.isfinite(g)) for g in gradients))
                values = [float(v.detach().cpu()) for v in z]
                refractory = float(torch.tensor(1e-6, dtype=dtype))
                expected = occupation_oracle(values, .25, refractory)
                self.assertLess(abs(float(actual.active_time.detach().cpu())/expected-1),
                                2e-5 if dtype == torch.float32 else 2e-7)
                def reference(x):
                    row = values.copy(); row[0] = x
                    return occupation_oracle(row, .25, refractory)
                full = five_point_derivative(reference, values[0], 1e-7)
                half = five_point_derivative(reference, values[0], 5e-8)
                self.assertLess(abs(full/half-1), 1e-6)
                self.assertLess(abs(float(gradients[0].cpu())/half-1),
                                2e-3 if dtype == torch.float32 else 2e-5)

    def test_released_atom_parameter_gradients_are_finite(self):
        refractory, remaining = .125, 2.**-20
        for device in DEVICES:
            for dtype in DTYPES:
                parameters = inputs((-.1, .3, .15), dtype, device, True)
                actual = finite_horizon_value(TensorDiffusion(*parameters), TensorReset(.25, refractory, 0.),
                                               0., refractory+remaining, active_reward=1.)
                gradients = torch.autograd.grad(actual.active_time, parameters)
                self.assertTrue(all(bool(torch.isfinite(g)) for g in gradients))
                self.assertEqual(float(gradients[0].cpu()), 0.)
                self.assertEqual(float(gradients[1].cpu()), 0.)
                mu, sigma, q = [float(v.detach().cpu()) for v in parameters]
                base = positive_occupation(.25, remaining, mu, sigma, q)
                moment = positive_occupation(.25, remaining, mu, sigma, q, discount_derivative=True)
                expected = math.exp(-q*refractory)*(moment-refractory*base)
                self.assertLess(abs(float(gradients[2].cpu())/expected-1),
                                2e-5 if dtype == torch.float32 else 1e-10)

    def test_higher_order_derivative_is_not_silently_qualified(self):
        z = torch.tensor(-1., dtype=torch.float64, requires_grad=True)
        first = torch.autograd.grad(log_normal_cdf(z), z, create_graph=True)[0]
        with self.assertRaises(RuntimeError):
            torch.autograd.grad(first, z)


if __name__ == "__main__":
    unittest.main()
