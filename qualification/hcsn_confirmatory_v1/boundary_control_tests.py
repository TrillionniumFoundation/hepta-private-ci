"""Uniformization/impulse equivalence and solve-gradient checks; toy-only data."""
import itertools
import unittest

import torch

from qualification.hcsn_adaptive.finite_control import evaluate_impulse_policy
from .boundary_control import process, soft_value
from .environment import execution_identity


class BoundaryControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        execution_identity()

    def test_every_hard_policy_matches_full_impulse_value(self):
        g, payoff, discount, _ = process()
        reward = torch.tensor([-.9, .3, -.2, .8, .4, -.03], dtype=g.dtype)
        for bits in itertools.product((False, True), repeat=5):
            policy = torch.tensor(bits, dtype=torch.bool)
            reference = evaluate_impulse_policy(g, reward, payoff, discount=discount,
                                               active_count=5, reset_entry=5, policy=policy)
            actual = soft_value(g, reward, payoff, discount, policy.to(g))
            torch.testing.assert_close(actual, reference, rtol=1e-10, atol=1e-11)

    def test_full_return_gradient_matches_finite_difference(self):
        g, payoff, discount, initial = process()
        reward = torch.tensor([-.9, .3, -.2, .8, .4, -.03], dtype=g.dtype)
        logits = torch.linspace(-.5, .5, 5, dtype=g.dtype, requires_grad=True)
        objective = initial @ soft_value(g, reward, payoff, discount, logits.sigmoid())
        gradient, = torch.autograd.grad(objective, logits)
        estimates = []
        for i in range(5):
            delta = torch.zeros_like(logits)
            delta[i] = 1e-6
            plus = initial @ soft_value(g, reward, payoff, discount, (logits + delta).sigmoid())
            minus = initial @ soft_value(g, reward, payoff, discount, (logits - delta).sigmoid())
            estimates.append((plus - minus) / 2e-6)
        torch.testing.assert_close(gradient, torch.stack(estimates), rtol=1e-6, atol=1e-8)


if __name__ == "__main__":
    unittest.main()

