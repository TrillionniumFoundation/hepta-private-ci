"""Independent matrix exponential, semigroup, and gradient contracts."""

import unittest

import torch

from experiments.call_put_stable_flow.memory import exact_delta_step


class MemoryTests(unittest.TestCase):
    def test_general_key_matches_augmented_matrix_exponential(self):
        torch.manual_seed(9)
        for scale in (0.0, 1e-12, 0.25, 1.0, 4.0):
            m = torch.randn(2, 3, dtype=torch.float64)
            k = torch.randn(3, dtype=torch.float64) * scale
            v = torch.randn(2, dtype=torch.float64)
            leak, write, dt = map(lambda x: torch.tensor(x, dtype=torch.float64), (0.07, 1.3, 0.8))
            observed = exact_delta_step(m, k, v, leak, write, dt)
            generator = -leak * torch.eye(3, dtype=torch.float64) - write * torch.outer(k, k)
            expected = []
            for row, target in zip(m, v):
                augmented = torch.zeros(4, 4, dtype=torch.float64)
                augmented[:3, :3] = generator
                augmented[:3, 3] = write * target * k
                expected.append((torch.matrix_exp(dt * augmented) @ torch.cat((row, torch.ones(1))))[:3])
            torch.testing.assert_close(observed, torch.stack(expected), rtol=2e-12, atol=2e-12)

    def test_semigroup_contraction_and_zero_dt(self):
        torch.manual_seed(17)
        m, n = torch.randn(2, 3, 4, dtype=torch.float64), torch.randn(2, 3, 4, dtype=torch.float64)
        k, v = torch.randn(2, 4, dtype=torch.float64), torch.randn(2, 3, dtype=torch.float64)
        leak, write = torch.tensor([0.0, 0.3]), torch.tensor([0.8, 0.0])
        first = exact_delta_step(m, k, v, leak, write, 0.3)
        second = exact_delta_step(first, k, v, leak, write, 0.7)
        whole = exact_delta_step(m, k, v, leak, write, 1.0)
        torch.testing.assert_close(second, whole, rtol=2e-8, atol=2e-8)
        changed = exact_delta_step(n, k, v, leak, write, 1.0)
        self.assertTrue(torch.all(torch.linalg.matrix_norm(whole - changed) <=
                                  torch.exp(-leak) * torch.linalg.matrix_norm(m - n) + 1e-7))
        torch.testing.assert_close(exact_delta_step(m, k, v, leak, write, 0.0), m, rtol=0, atol=0)

    def test_autograd_at_zero_key_zero_rates_and_near_zero_key(self):
        torch.manual_seed(23)
        for key_scale, leak_value, write_value in ((0.0, 0.0, 0.0), (1e-8, 1e-8, 0.4), (0.7, 0.1, 0.8)):
            args = (torch.randn(2, 3, dtype=torch.float64),
                    torch.randn(3, dtype=torch.float64) * key_scale,
                    torch.randn(2, dtype=torch.float64),
                    torch.tensor(leak_value, dtype=torch.float64),
                    torch.tensor(write_value, dtype=torch.float64), torch.tensor(0.7, dtype=torch.float64))
            args = tuple(x.requires_grad_() for x in args)
            self.assertTrue(torch.autograd.gradcheck(exact_delta_step, args, eps=1e-6, atol=1e-6, rtol=1e-5))


if __name__ == "__main__":
    unittest.main()
