"""Enumerated stochastic gradients and multiplier chronology, not fit scores."""

import itertools
import math
import unittest

import torch

from .objective import ARMS, DualState, objective


class ObjectiveTests(unittest.TestCase):
    def test_enumerated_score_gradient_matches_population_lagrangian(self):
        probability, gamma, multiplier = .37, 2., .7
        for arm in ARMS:
            expected_gradient = 0.
            for outcomes in itertools.product((0., 1.), repeat=2):
                logit = torch.tensor(math.log(probability / (1 - probability)),
                                     dtype=torch.float64, requires_grad=True)
                y = torch.tensor([outcomes], dtype=torch.float64)
                logp = y * torch.nn.functional.logsigmoid(logit) + (1 - y) * torch.nn.functional.logsigmoid(-logit)
                loss, _ = objective(logp, y, y.bool(), logit * 0,
                    arm=arm, dual=DualState(multiplier), gamma=gamma, auxiliary_weight=0.)
                weight = math.prod(probability if x else 1 - probability for x in outcomes)
                expected_gradient += weight * float(torch.autograd.grad(loss, logit)[0])
            transformed_gap = -1. if arm == "mean" else math.expm1(-gamma) / gamma
            if arm == "risk_success":
                transformed_gap -= multiplier
            analytic = probability * (1 - probability) * transformed_gap
            self.assertAlmostEqual(expected_gradient, analytic, places=11, msg=arm)

    def test_current_gradient_uses_pre_emission_dual_not_updated_dual(self):
        before = DualState(.2, 3)
        after = before.advance(.5, rate=.1, cap=5.)
        logp = torch.tensor([[.1, .2]], requires_grad=True)
        utility = torch.tensor([[0., 1.]])
        success = utility.bool()
        _, stats = objective(logp, utility, success, logp.sum() * 0,
                              arm="risk_success", dual=before)
        self.assertEqual(before, DualState(.2, 3))
        self.assertEqual(after, DualState(.25, 4))
        self.assertEqual(stats["dual_used_before_current_emission"], .2)

    def test_rejects_differentiable_reward_and_non_boolean_success(self):
        logp = torch.tensor([[.1, .2]], requires_grad=True)
        utility = torch.tensor([[0., 1.]])
        for scores, success in ((utility.requires_grad_(), utility.bool()),
                                (utility.detach(), utility.detach())):
            with self.assertRaises(ValueError):
                objective(logp, scores, success, logp.sum() * 0,
                          arm="risk_success", dual=DualState())

    def test_projected_dual_retains_failure_direction_and_bounds(self):
        self.assertEqual(DualState(0.).advance(-.5, rate=.1, cap=5.), DualState(0., 1))
        self.assertEqual(DualState(5.).advance(.5, rate=.1, cap=5.), DualState(5., 1))
        for gap in (float("nan"), float("inf"), 1.1):
            with self.assertRaises(ValueError):
                DualState().advance(gap, rate=.1, cap=5.)


if __name__ == "__main__":
    unittest.main()
