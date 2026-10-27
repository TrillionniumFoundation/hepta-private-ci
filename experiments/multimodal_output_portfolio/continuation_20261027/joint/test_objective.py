"""Behavioral checks for moment learning and its actual greedy deployment."""

import math
import unittest

import torch

from .training import predicted_moment


class MomentLearningTests(unittest.TestCase):
    def test_fit_conditional_moment_can_reverse_mean_choice(self):
        # The second plan has the larger mean and the worse entropic CE.
        utility = torch.tensor([[.6, 1.], [.6, .3]], dtype=torch.float64)
        target = torch.exp(-2 * utility)
        raw = torch.nn.Parameter(torch.zeros(2, dtype=torch.float64))
        optimizer = torch.optim.Adam([raw], lr=.03)
        for _ in range(1600):
            optimizer.zero_grad(set_to_none=True)
            (predicted_moment(raw)[None] - target).square().mean().backward()
            optimizer.step()
        self.assertEqual(int(utility.mean(0).argmax()), 1)
        self.assertEqual(int(raw.argmax()), 0)
        self.assertTrue(torch.allclose(predicted_moment(raw), target.mean(0), atol=2e-5, rtol=0))

    def test_actual_moment_objective_gradient(self):
        raw = torch.tensor([[.3, -.6], [1.2, -.4]], dtype=torch.float64, requires_grad=True)
        outcomes = torch.tensor([[.8, -.2], [.1, .5]], dtype=torch.float64)
        target = torch.exp(-2 * outcomes)
        loss = (predicted_moment(raw) - target).square().mean()
        analytic, = torch.autograd.grad(loss, raw)
        numerical = torch.zeros_like(raw)
        epsilon = 1e-6
        for i in range(raw.numel()):
            plus, minus = raw.detach().clone(), raw.detach().clone()
            plus.reshape(-1)[i] += epsilon
            minus.reshape(-1)[i] -= epsilon
            numerical.reshape(-1)[i] = (((predicted_moment(plus) - target).square().mean()
                                         - (predicted_moment(minus) - target).square().mean()) / (2 * epsilon))
        self.assertTrue(torch.allclose(analytic, numerical, atol=1e-8, rtol=1e-7))

    def test_complete_distribution_differs_from_mean_utility_substitution(self):
        outcomes = torch.tensor([1., .3], dtype=torch.float64)
        actual = torch.exp(-2 * outcomes).mean().item()
        substituted = math.exp(-2 * outcomes.mean().item())
        self.assertGreater(actual, substituted)
        self.assertLess(-math.log(actual) / 2, .6)
        self.assertGreater(float(outcomes.mean()), .6)


if __name__ == "__main__":
    unittest.main()
