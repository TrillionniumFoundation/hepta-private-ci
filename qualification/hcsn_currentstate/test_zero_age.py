"""Independent scalar renewal values and derivatives at exact release edges."""

from dataclasses import replace
from fractions import Fraction as F
import math
import unittest

import torch

from .differentiable import Flux, Physics, Work, advance, initial, refractory


torch.set_num_threads(1)


class ZeroAgeReleaseTests(unittest.TestCase):
    def test_future_release_keeps_alpha_gradient_with_one_actual_exponential(self):
        rate = torch.tensor(1.3, dtype=torch.float64, requires_grad=True)
        alpha = torch.tensor([[.8], [-.4]], dtype=torch.float64, requires_grad=True)
        packet = Flux(F(1), F(2), alpha, -rate.reshape(1, 1), rate[None], rate.new_ones(1))
        state = replace(initial(torch.zeros_like(alpha)), pending=(packet,))
        work = Work(max_exponentials=1)
        actual = refractory(state, work)
        expected = alpha[:, 0] * -torch.expm1(-rate)
        torch.testing.assert_close(actual, expected, atol=2e-15, rtol=2e-14)
        self.assertEqual(work.exponentials, 1)
        actual_grad = torch.autograd.grad(actual.sum(), (alpha, rate), create_graph=True)
        expected_grad = torch.autograd.grad(expected.sum(), (alpha, rate), create_graph=True)
        for actual_g, expected_g in zip(actual_grad, expected_grad):
            torch.testing.assert_close(actual_g, expected_g, atol=2e-15, rtol=2e-14)
        actual_second, = torch.autograd.grad(actual_grad[1], (rate,))
        expected_second, = torch.autograd.grad(expected_grad[1], (rate,))
        torch.testing.assert_close(actual_second, expected_second, atol=2e-15, rtol=2e-14)

    def test_positive_release_age_is_still_evolved_and_charged(self):
        rate = torch.tensor(1.3, dtype=torch.float64, requires_grad=True)
        alpha = rate.new_tensor([[.8], [-.4]])
        packet = Flux(F(1), F(2), alpha, -rate.reshape(1, 1), rate[None], rate.new_ones(1))
        state = replace(initial(torch.zeros_like(alpha)), time=F(3, 2), pending=(packet,))
        with self.assertRaisesRegex(RuntimeError, "work budget exhausted"):
            refractory(state, Work(max_exponentials=1))
        work = Work(max_exponentials=2)
        actual = refractory(state, work)
        expected = alpha[:, 0] * (torch.exp(-rate / 2) - torch.exp(-rate))
        torch.testing.assert_close(actual, expected, atol=2e-15, rtol=2e-14)
        self.assertEqual(work.exponentials, 2)
        actual_grad, = torch.autograd.grad(actual.sum(), (rate,))
        expected_grad, = torch.autograd.grad(expected.sum(), (rate,))
        torch.testing.assert_close(actual_grad, expected_grad, atol=2e-15, rtol=2e-14)

    def test_multiple_exact_release_edges_match_gamma_values_and_hessian(self):
        for dtype, atol, rtol in ((torch.float64, 3e-13, 3e-12), (torch.float32, 3e-6, 3e-5)):
            with self.subTest(dtype=dtype):
                rate = torch.tensor(1.7, dtype=dtype, requires_grad=True)
                alpha = torch.tensor([[1.], [-.4], [.3]], dtype=dtype, requires_grad=True)
                z = rate.new_zeros(())
                law = Physics(-rate.reshape(1, 1), rate[None], z[None], rate.new_ones(1),
                              z[None], z, z, z, F(1, 5))
                state = advance(initial(alpha), law, F(63, 100))
                actual = torch.cat((state.active[:, 0], state.hits, refractory(state)))

                def hits(time):
                    total = rate.new_zeros(())
                    for k in range(1, 5):
                        remaining = time - (k - 1) * .2
                        if remaining > 0:
                            x = rate * remaining
                            total = total + 1 - torch.exp(-x) * sum(
                                x ** j / math.factorial(j) for j in range(k))
                    return total

                count = hits(.63)
                waiting = count - hits(.43)
                expected = torch.cat(tuple(alpha[:, 0] * scale for scale in (1 - waiting, count, waiting)))
                torch.testing.assert_close(actual, expected, atol=atol, rtol=rtol)
                weights = torch.linspace(-.7, 1.2, actual.numel(), dtype=dtype)
                actual_grad = torch.autograd.grad(actual @ weights, (rate, alpha), create_graph=True)
                expected_grad = torch.autograd.grad(expected @ weights, (rate, alpha), create_graph=True)
                for observed, reference in zip(actual_grad, expected_grad):
                    torch.testing.assert_close(observed, reference, atol=atol, rtol=rtol)
                actual_second, = torch.autograd.grad(actual_grad[0], (rate,))
                expected_second, = torch.autograd.grad(expected_grad[0], (rate,))
                torch.testing.assert_close(actual_second, expected_second, atol=atol, rtol=rtol)


if __name__ == "__main__":
    unittest.main()
