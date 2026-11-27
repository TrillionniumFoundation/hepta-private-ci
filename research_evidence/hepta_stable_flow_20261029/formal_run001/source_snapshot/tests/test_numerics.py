"""Independent Decimal value/derivative oracles, including tiny boundary values."""

import decimal
import math
import unittest

import torch

from experiments.call_put_stable_flow.numerics import call_put, phi1, phi2


def phi_reference(value, order):
    if value == 0:
        return 1.0 / math.factorial(order), 1.0 / math.factorial(order + 1)
    with decimal.localcontext() as ctx:
        ctx.prec = 90
        z = decimal.Decimal.from_float(value)
        result = decimal.Decimal(0)
        derivative = decimal.Decimal(0)
        for j in range(180):
            result += z**j / decimal.Decimal(math.factorial(j + order))
            if j:
                derivative += (
                    j * z ** (j - 1) / decimal.Decimal(math.factorial(j + order))
                )
        return float(result), float(derivative)


def option_reference(x_value, k_value):
    with decimal.localcontext() as ctx:
        ctx.prec = 90
        x = decimal.Decimal.from_float(x_value)
        k = decimal.Decimal.from_float(k_value)
        one = decimal.Decimal(1)
        beta = k / (one + k)
        if x <= 0:
            return (
                0.0,
                float(one - beta * x.exp()),
                0.0,
                0.0,
                float(-beta * x.exp()),
                float(-x.exp() / (one + k) ** 2),
            )
        ex = x.exp()
        ek = (-k * x).exp()
        d = k * ex + ek
        dx = k * (ex - ek)
        dk = ex - x * ek
        a = (d - (one + k)) / d
        p = ek / (one + k)
        return tuple(
            map(
                float,
                (
                    a,
                    p,
                    (one + k) * dx / d**2,
                    ((one + k) * dk - d) / d**2,
                    -k * p,
                    -p * (x + one / (one + k)),
                ),
            )
        )


class NumericsTests(unittest.TestCase):
    def assert_relative(self, actual, expected, tolerance, dtype):
        self.assertTrue(math.isfinite(actual))
        if expected == 0:
            self.assertEqual(actual, 0.0)
        elif abs(expected) < 16 * torch.finfo(dtype).tiny:
            self.assertLessEqual(abs(actual - expected), 16 * torch.finfo(dtype).tiny)
        else:
            self.assertLessEqual(abs(actual / expected - 1.0), tolerance)

    def test_phi_values_and_actual_autograd_against_decimal(self):
        grid = [
            -20,
            -4,
            -1.0000001,
            -1,
            -0.2500001,
            -0.25,
            -0.1,
            -1e-4,
            -1e-8,
            0,
            1e-8,
            1e-4,
            0.25,
            0.2500001,
            1,
            1.0000001,
            4,
            20,
        ]
        for dtype, tolerance in [(torch.float32, 1e-5), (torch.float64, 1e-11)]:
            for order, function in [(1, phi1), (2, phi2)]:
                for item in grid:
                    with self.subTest(dtype=dtype, order=order, z=item):
                        z = torch.tensor(item, dtype=dtype, requires_grad=True)
                        result = function(z)
                        (gradient,) = torch.autograd.grad(result, z)
                        expected, expected_gradient = phi_reference(
                            float(z.detach()), order
                        )
                        self.assert_relative(
                            float(result.detach()), expected, tolerance, dtype
                        )
                        self.assert_relative(
                            float(gradient), expected_gradient, tolerance, dtype
                        )

    def test_call_put_values_and_gradients_against_decimal(self):
        grid = [
            -20,
            -0.25,
            -1e-8,
            0,
            1e-12,
            1e-8,
            1e-4,
            0.01,
            0.0625,
            0.250001,
            0.5,
            2,
            20,
            80,
        ]
        for dtype, tolerance in [(torch.float32, 1e-5), (torch.float64, 1e-11)]:
            for k in [0.25, 1.0, 4.0]:
                for item in grid:
                    with self.subTest(dtype=dtype, kappa=k, x=item):
                        x = torch.tensor(item, dtype=dtype, requires_grad=True)
                        kappa = torch.tensor(k, dtype=dtype, requires_grad=True)
                        a, p = call_put(x, kappa)
                        ax, ak = torch.autograd.grad(a, (x, kappa), retain_graph=True)
                        px, pk = torch.autograd.grad(p, (x, kappa))
                        expected = option_reference(
                            float(x.detach()), float(kappa.detach())
                        )
                        for actual, wanted in zip((a, p, ax, ak, px, pk), expected):
                            self.assert_relative(
                                float(actual.detach()), wanted, tolerance, dtype
                            )

    def test_c1_matching_and_finite_inactive_branches(self):
        for mode in ["analytic", "matched_c1"]:
            x = torch.tensor([-1e-8, 0, 1e-8], dtype=torch.float64, requires_grad=True)
            k = torch.tensor(1.3, dtype=torch.float64, requires_grad=True)
            a, p = call_put(x, k, mode)
            (ax,) = torch.autograd.grad(a.sum(), x, retain_graph=True)
            (px,) = torch.autograd.grad(p.sum(), x)
            torch.testing.assert_close(ax, torch.zeros_like(ax), rtol=0, atol=2e-8)
            torch.testing.assert_close(
                px, torch.full_like(px, -1.3 / 2.3), rtol=0, atol=2e-8
            )
            self.assertEqual(a[1].item(), 0.0)
            self.assertAlmostEqual(p[1].item(), 1 / 2.3, places=15)
        for mode in ["analytic", "matched_c1", "sigmoid"]:
            x = torch.tensor([-1000.0, -1.0, 0.0, 1.0, 1000.0], requires_grad=True)
            k = torch.tensor(4.0, requires_grad=True)
            a, p = call_put(x, k, mode)
            gradients = torch.autograd.grad((a + p).sum(), (x, k))
            self.assertTrue(all(torch.isfinite(t).all() for t in (a, p, *gradients)))
            self.assertTrue(((a >= 0) & (a <= 1) & (p >= 0) & (p <= 1)).all())

    def test_mixed_batch_taylor_and_far_paths_preserve_scalar_results(self):
        for dtype, tolerance in [(torch.float32, 1e-6), (torch.float64, 1e-14)]:
            x = torch.tensor(
                [-2.0, 0.0, 1e-8, 0.04, 0.5, 3.0], dtype=dtype, requires_grad=True
            )
            k = torch.tensor(
                [0.25, 1.0, 4.0, 0.25, 1.0, 4.0], dtype=dtype, requires_grad=True
            )
            a, p = call_put(x, k)
            gx, gk = torch.autograd.grad((0.3 * a - 0.7 * p).sum(), (x, k))
            for index in range(x.numel()):
                xs = x[index].detach().clone().requires_grad_()
                ks = k[index].detach().clone().requires_grad_()
                scalar_a, scalar_p = call_put(xs, ks)
                scalar_gx, scalar_gk = torch.autograd.grad(
                    0.3 * scalar_a - 0.7 * scalar_p, (xs, ks)
                )
                torch.testing.assert_close(
                    torch.stack((a[index], p[index])),
                    torch.stack((scalar_a, scalar_p)),
                    rtol=0,
                    atol=0,
                )
                torch.testing.assert_close(
                    torch.stack((gx[index], gk[index])),
                    torch.stack((scalar_gx, scalar_gk)),
                    rtol=tolerance,
                    atol=0,
                )


if __name__ == "__main__":
    unittest.main()
