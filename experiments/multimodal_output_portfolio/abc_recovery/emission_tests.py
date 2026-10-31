"""Actual sampling, likelihood and score-gradient checks; fixtures are synthetic."""

import itertools
import math
import unittest

import torch
from torch.nn import functional as F

from ..v6.data import BOS, CAPTION_LENGTH, EOS, PAD, Observation, Target
from ..v7.model import SlotPortfolio
from .emission import output_digests, sample_emission, score_function_objective


def public_fixture(batch=4):
    rng = torch.Generator().manual_seed(803)
    pixels = torch.rand((batch, 1, 28, 56), generator=rng)
    tokens = torch.tensor([BOS, 9, 12, 11, 13, 11, EOS, PAD]).repeat(batch, 1)
    tokens[:, 1] += torch.arange(batch) % 2
    return Observation(pixels, torch.ones_like(pixels), tokens)


class EmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(2)

    def setUp(self):
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(17)
            self.model = SlotPortfolio().eval()
        self.state = self.model.encode(public_fixture())
        self.state = self.model.step(self.state, "refine_semantic")

    def test_same_rng_replays_actual_contents_in_gradient_and_deployment_modes(self):
        global_before = torch.get_rng_state().clone()
        a = sample_emission(self.model, self.state,
                            generator=torch.Generator().manual_seed(91))
        with torch.no_grad():
            b = sample_emission(self.model, self.state,
                                generator=torch.Generator().manual_seed(91))
        self.assertTrue(torch.equal(a.pixels, b.pixels))
        self.assertTrue(torch.equal(a.tokens, b.tokens))
        self.assertEqual(a.row_sha256, b.row_sha256)
        self.assertEqual((a.rng_before_sha256, a.rng_after_sha256),
                         (b.rng_before_sha256, b.rng_after_sha256))
        self.assertNotEqual(a.rng_before_sha256, a.rng_after_sha256)
        self.assertTrue(torch.equal(global_before, torch.get_rng_state()))
        self.assertFalse(a.pixels.requires_grad)
        self.assertFalse(a.tokens.requires_grad)
        self.assertTrue(a.log_probability.requires_grad)
        self.assertFalse(b.log_probability.requires_grad)
        changed = a.pixels.clone()
        changed[0, 0, 0, 0] = 1 - changed[0, 0, 0, 0]
        self.assertNotEqual(output_digests(changed, a.tokens)[0], a.row_sha256[0])

    def test_likelihood_is_for_the_actual_autoregressive_prefix_and_pixels(self):
        emission = sample_emission(self.model, self.state,
                                   generator=torch.Generator().manual_seed(615))
        initial = torch.tanh(self.model.text_initial(
            torch.cat((self.state.h, self.state.text), 1))).unsqueeze(0)
        sequence, _ = self.model.text_decoder(
            self.model.token_embedding(emission.tokens[:, :-1]), initial)
        logits = self.model.text_projection(sequence)
        selected = logits.log_softmax(-1).gather(
            2, emission.tokens[:, 1:, None]).squeeze(-1)
        active = torch.cat((torch.ones((4, 1), dtype=torch.bool),
                            (emission.tokens[:, 1:-1] != EOS).cumprod(1).bool()), 1)
        expected_text = (selected * active).sum(1)
        pixel_logits = self.model.decode(self.state).image_logits
        expected_image = (emission.pixels * -F.softplus(-pixel_logits)
                          + (1 - emission.pixels) * -F.softplus(pixel_logits)).flatten(1).sum(1)
        torch.testing.assert_close(emission.text_log_probability, expected_text)
        torch.testing.assert_close(emission.image_log_probability, expected_image)
        torch.testing.assert_close(emission.log_probability, expected_text + expected_image)

    def test_eos_stops_sampling_and_likelihood_without_inventing_an_eos(self):
        with torch.no_grad():
            self.model.text_projection.weight.zero_()
            self.model.text_projection.bias.fill_(-1000)
            self.model.text_projection.bias[EOS] = 1000
        emission = sample_emission(self.model, self.state,
                                   generator=torch.Generator().manual_seed(45))
        expected = torch.tensor([BOS, EOS] + [PAD] * (CAPTION_LENGTH - 2)).repeat(4, 1)
        self.assertTrue(torch.equal(emission.tokens, expected))
        torch.testing.assert_close(emission.text_log_probability, torch.zeros(4))
        with torch.no_grad():
            self.model.text_projection.bias[EOS] = -1000
            self.model.text_projection.bias[3] = 1000
        without_eos = sample_emission(self.model, self.state,
                                      generator=torch.Generator().manual_seed(45))
        self.assertTrue(torch.equal(without_eos.tokens,
                                   torch.tensor([BOS] + [3] * 7).repeat(4, 1)))

    def test_actual_output_score_gradient_reaches_shared_cells_and_both_decoders(self):
        state = self.model.step(self.state, "couple")
        emission = sample_emission(self.model, state,
                                   generator=torch.Generator().manual_seed(331))
        losses = (.3 * emission.pixels.mean((1, 2, 3))
                  + .7 * ((emission.tokens[:, 1] % 5).float() / 4) - .5).reshape(2, 2)
        estimate = score_function_objective(emission.log_probability.reshape(2, 2),
                                             losses, risk_aversion=2.)
        estimate.surrogate.backward()
        for module in (self.model.pixel_encoder, self.model.semantic_cell,
                       self.model.coupling_cell, self.model.pixel_decoder,
                       self.model.text_initial, self.model.text_decoder,
                       self.model.text_projection):
            magnitude = sum(float(p.grad.abs().sum()) for p in module.parameters()
                            if p.grad is not None)
            self.assertGreater(magnitude, 0)
        self.assertTrue(all(p.grad is None for p in self.model.digit_head.parameters()))

    def test_sampler_rejects_truth_and_requires_an_explicit_rng(self):
        truth = Target(torch.zeros((4, 1, 28, 56)), torch.zeros((4, 8), dtype=torch.long),
                       torch.zeros((4, 2), dtype=torch.long))
        with self.assertRaises(TypeError):
            sample_emission(self.model, truth, generator=torch.Generator())
        with self.assertRaises(TypeError):
            sample_emission(self.model, self.state, generator=torch.Generator(), target=truth)
        with self.assertRaises(TypeError):
            sample_emission(self.model, self.state)


class ScoreFunctionTests(unittest.TestCase):
    def test_leave_one_out_gradient_matches_exact_bernoulli_expectation(self):
        for gamma in (0., 2.):
            logit = torch.tensor(.37, dtype=torch.float64, requires_grad=True)
            probability = float(logit.detach().sigmoid())
            expected_gradient = 0.
            for outcomes in itertools.product((0., 1.), repeat=2):
                outcomes = torch.tensor(outcomes, dtype=torch.float64).reshape(1, 2)
                logp = -F.binary_cross_entropy_with_logits(
                    logit.expand_as(outcomes), outcomes, reduction="none")
                losses = -.6 + 1.2 * outcomes
                estimate = score_function_objective(logp, losses, risk_aversion=gamma)
                gradient, = torch.autograd.grad(estimate.surrogate, logit)
                ones = int(outcomes.sum())
                joint_probability = probability ** ones * (1 - probability) ** (2 - ones)
                expected_gradient += joint_probability * float(gradient)
            transform = ((lambda loss: loss) if gamma == 0 else
                         (lambda loss: math.expm1(gamma * loss) / gamma))
            analytic = probability * (1 - probability) * (transform(.6) - transform(-.6))
            self.assertAlmostEqual(expected_gradient, analytic, places=12)

    def test_joint_and_mean_conditional_ce_are_reported_as_distinct_estimands(self):
        losses = torch.tensor([[-1., -1.], [1., 1.]])
        estimate = score_function_objective(torch.zeros_like(losses), losses, risk_aversion=2.)
        self.assertEqual(estimate.empirical_mean_conditional_loss_ce, 0.)
        self.assertGreater(estimate.empirical_joint_loss_ce, .5)
        self.assertAlmostEqual(estimate.empirical_exponential_moment, math.cosh(2.))
        self.assertFalse(estimate.advantage.requires_grad)

    def test_missing_independent_draws_and_differentiable_scored_output_are_rejected(self):
        with self.assertRaises(ValueError):
            score_function_objective(torch.zeros((3, 1)), torch.zeros((3, 1)), risk_aversion=2.)
        with self.assertRaises(ValueError):
            score_function_objective(torch.zeros((1, 2)),
                                      torch.zeros((1, 2), requires_grad=True), risk_aversion=2.)
        with self.assertRaises(FloatingPointError):
            score_function_objective(torch.zeros((1, 2)), torch.full((1, 2), 1000.),
                                      risk_aversion=2.)


if __name__ == "__main__":
    unittest.main()
