"""Exact finite-law and Gaussian score checks; no stochastic test tolerances."""

import math
import unittest

import torch

from .learning import (
    actor_score_loss, actual_suffix_returns, critic_log_moment_loss,
    moment_score_terms, population_metrics,
)


DTYPE = torch.float64


class ScoreLearningTests(unittest.TestCase):
    def test_binary_exact_law_matches_direct_derivative_and_finite_difference(self):
        for gamma in (0.0, 2.0):
            z = torch.tensor(0.3, dtype=DTYPE, requires_grad=True)
            p = z.sigmoid()
            law = torch.stack((p, 1 - p))
            returns = torch.tensor((0.85, -0.3), dtype=DTYPE)
            terms = moment_score_terms(law.log(), returns, gamma=gamma)
            score = torch.autograd.grad((law.detach() * terms).sum(), z)[0]

            def objective(value):
                chance = torch.tensor(value, dtype=DTYPE).sigmoid()
                costs = -returns if gamma == 0 else torch.expm1(-gamma * returns) / gamma
                return chance * costs[0] + (1 - chance) * costs[1]

            epsilon = 1e-5
            finite = (objective(0.3 + epsilon) - objective(0.3 - epsilon)) / (2 * epsilon)
            self.assertAlmostEqual(float(score), float(finite), places=9)

    def test_stop_and_variable_length_joint_scores_match_full_path_law(self):
        logits = torch.tensor((0.2, -0.4), dtype=DTYPE, requires_grad=True)
        stop, repair = logits.sigmoid().unbind()
        # STOP, CONTINUE+REPAIR+forced STOP, CONTINUE+DELIVER. Costs differ.
        law = torch.stack((stop, (1 - stop) * repair, (1 - stop) * (1 - repair)))
        returns = torch.tensor((0.3 - 0.04, 0.9 - 0.2, -0.1 - 0.08), dtype=DTYPE)
        terms = moment_score_terms(law.log(), returns)
        score = torch.autograd.grad((law.detach() * terms).sum(), logits, retain_graph=True)[0]
        direct = torch.autograd.grad((law * torch.expm1(-2 * returns) / 2).sum(), logits)[0]
        torch.testing.assert_close(score, direct, rtol=1e-12, atol=1e-12)

    def test_leave_one_out_is_unbiased_over_all_independent_ordered_pairs(self):
        z = torch.tensor(0.25, dtype=DTYPE, requires_grad=True)
        p = z.sigmoid()
        law = torch.stack((p, 1 - p))
        returns = torch.tensor((0.7, -0.2), dtype=DTYPE)
        expected_loss = z * 0
        for first in range(2):
            for second in range(2):
                indexes = [first, second]
                loss, _ = actor_score_loss(law.log()[indexes], returns[indexes], independent_episodes=True)
                expected_loss = expected_loss + (law[first] * law[second]).detach() * loss
        actual = torch.autograd.grad(expected_loss, z, retain_graph=True)[0]
        expected = torch.autograd.grad((law * torch.expm1(-2 * returns) / 2).sum(), z)[0]
        torch.testing.assert_close(actual, expected, rtol=1e-12, atol=1e-12)

    def test_singleton_baseline_keeps_gradient_and_correlated_loo_rejects(self):
        score = torch.tensor([-0.8], dtype=DTYPE, requires_grad=True)
        loss, stats = actor_score_loss(score, [0.4])
        self.assertEqual(stats["baseline"], "zero_singleton")
        self.assertNotEqual(float(torch.autograd.grad(loss, score)[0][0]), 0.0)
        with self.assertRaisesRegex(ValueError, "independent"):
            actor_score_loss(score.expand(2), [0.4, -0.2], independent_episodes=False)

    def test_readback_return_has_no_duplicate_pathwise_gradient(self):
        score = torch.tensor([-0.8], dtype=DTYPE, requires_grad=True)
        observed = torch.tensor([0.4], dtype=DTYPE, requires_grad=True)
        loss, stats = actor_score_loss(score, observed)
        score_gradient, reward_gradient = torch.autograd.grad(loss, (score, observed), allow_unused=True)
        self.assertIsNotNone(score_gradient)
        self.assertIsNone(reward_gradient)
        self.assertFalse(stats["self_normalized_risk_gradient"])
        self.assertFalse(stats["supervised_loss_included"])

    def test_gaussian_latent_score_matches_closed_form_population_moment(self):
        # Deterministic quadrature over held-fixed latents, not pathwise samples.
        mean = torch.tensor(0.2, dtype=DTYPE, requires_grad=True)
        log_scale = torch.tensor(math.log(0.4), dtype=DTYPE, requires_grad=True)
        scale = log_scale.exp()
        samples = torch.linspace(-6, 6, 6001, dtype=DTYPE)
        log_density = -0.5 * ((samples - mean) / scale).square() - log_scale - 0.5 * math.log(2 * math.pi)
        terms = moment_score_terms(log_density, samples)
        integral = torch.trapezoid(log_density.detach().exp() * terms, samples)
        score = torch.autograd.grad(integral, (mean, log_scale), retain_graph=True)
        exact = (torch.exp(-2 * mean + 2 * scale.square()) - 1) / 2
        direct = torch.autograd.grad(exact, (mean, log_scale))
        torch.testing.assert_close(torch.stack(score), torch.stack(direct), rtol=1e-9, atol=1e-9)

    def test_mean_control_still_reports_fixed_gamma_population_risk(self):
        score = torch.tensor([-0.4, -0.8], dtype=DTYPE, requires_grad=True)
        _, stats = actor_score_loss(score, [0.9, -0.4], gamma=0, baseline="none")
        self.assertEqual(stats["training_gamma"], 0.0)
        self.assertEqual(stats["evaluation_gamma"], 2.0)
        self.assertIn("finite_sample", stats["ce_estimate_bias"])
        expected = -torch.logsumexp(torch.tensor([-1.8, 0.8], dtype=DTYPE), 0) / 2 + math.log(2) / 2
        self.assertAlmostEqual(stats["population_ce_plugin"], float(expected), places=13)


class ConditionalMomentTests(unittest.TestCase):
    def test_proper_loss_targets_log_expected_moment_not_mean_log_sample(self):
        returns = torch.tensor([-0.5, 0.8], dtype=DTYPE)
        optimum = torch.exp(-2 * returns).mean().log().detach().requires_grad_()
        loss, _ = critic_log_moment_loss(optimum.expand(2), returns)
        self.assertAlmostEqual(float(torch.autograd.grad(loss, optimum)[0]), 0.0, places=13)
        wrong = (-2 * returns).mean().detach().requires_grad_()
        loss, stats = critic_log_moment_loss(wrong.expand(2), returns)
        self.assertGreater(abs(float(torch.autograd.grad(loss, wrong)[0])), 0.1)
        self.assertFalse(stats["target_log_sample_regression"])

    def test_critic_targets_and_input_features_are_detached(self):
        features = torch.ones(2, 3, dtype=DTYPE, requires_grad=True)
        head = torch.nn.Linear(3, 1, dtype=DTYPE)
        returns = torch.tensor([0.3, -0.2], dtype=DTYPE, requires_grad=True)
        predictions = head(features.detach()).flatten()
        loss, _ = critic_log_moment_loss(predictions, returns)
        gradients = torch.autograd.grad(loss, (head.weight, features, returns), allow_unused=True)
        self.assertIsNotNone(gradients[0])
        self.assertEqual(gradients[1:], (None, None))

    def test_suffix_costs_include_stopping_and_emission_once(self):
        actual = actual_suffix_returns(0.8, [0.1, 0.02, 0.18])
        torch.testing.assert_close(actual, torch.tensor([0.5, 0.6, 0.62], dtype=DTYPE), rtol=0, atol=1e-15)
        with self.assertRaisesRegex(ValueError, "negative"):
            actual_suffix_returns(0.8, [0.1, -0.02])

    def test_mean_critic_is_explicit_degenerate_log_moment(self):
        prediction = torch.zeros(2, dtype=DTYPE, requires_grad=True)
        loss, stats = critic_log_moment_loss(prediction, [0.3, -0.6], gamma=0)
        torch.testing.assert_close(torch.autograd.grad(loss, prediction)[0], torch.zeros_like(prediction))
        self.assertEqual(stats["target_moment_mean"], 1.0)

    def test_overflow_and_invalid_reward_domains_reject_without_clipping(self):
        with self.assertRaisesRegex(ValueError, "numeric domain"):
            actor_score_loss(torch.tensor([-0.3], requires_grad=True), [-1e5], baseline="none")
        with self.assertRaisesRegex(ValueError, "overflow"):
            critic_log_moment_loss(torch.tensor([1000.0], requires_grad=True), [0.1])
        with self.assertRaises(ValueError):
            population_metrics([float("nan")])


if __name__ == "__main__":
    unittest.main()
