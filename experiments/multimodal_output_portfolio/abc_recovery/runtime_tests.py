"""Synthetic-only tests of observable innovations, delayed effects and accounting."""

from collections import Counter
from dataclasses import fields, replace
import unittest

import torch

from ..v6.data import Observation, Target
from ..v7.model import SlotPortfolio
from .emission import output_digests, score_function_objective
from .runtime import (ACTIONS, FEATURE_DIM, PublicFrame, TransitionFailure, feasible_mask,
                      initialize, public_digest, public_features, public_frame, rollout,
                      transition, work_counts)


def observation_fixture(batch=3):
    pixels = torch.rand((batch, 1, 28, 56), generator=torch.Generator().manual_seed(32))
    tokens = torch.tensor([1, 9, 12, 11, 13, 11, 2, 0]).repeat(batch, 1)
    return Observation(pixels, torch.ones_like(pixels), tokens)


class RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(2)

    def setUp(self):
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(17)
            self.model = SlotPortfolio().eval()
        self.observation = observation_fixture()

    def test_future_rng_changes_actual_innovation_but_not_prior_frame_or_action(self):
        run = initialize(self.model, self.observation, generator=torch.Generator().manual_seed(7))
        choose = lambda frame: "refine_image" if frame.pixels.mean() >= 0 else "stop"
        before_a, before_b = public_frame(run), public_frame(run)
        self.assertEqual(public_digest(before_a), public_digest(before_b))
        action_a, action_b = choose(before_a), choose(before_b)
        self.assertEqual(action_a, action_b)
        a = transition(self.model, run, action_a, generator=torch.Generator().manual_seed(111))
        b = transition(self.model, run, action_b, generator=torch.Generator().manual_seed(222))
        self.assertEqual(a.ledger[-2], b.ledger[-2])
        self.assertEqual(a.ledger[-2]["phase"], "action_committed")
        self.assertNotEqual(a.ledger[-1]["innovation_rng_before_sha256"],
                            b.ledger[-1]["innovation_rng_before_sha256"])
        self.assertFalse(torch.equal(a.pixels, b.pixels))
        self.assertEqual(len(run.ledger), 1)

    def test_actual_draft_changes_features_and_masked_draft_does_not(self):
        run = initialize(self.model, self.observation, generator=torch.Generator().manual_seed(9))
        frame = public_frame(run)
        changed = replace(frame, pixels=1 - frame.pixels, tokens=(frame.tokens + 1) % 24)
        work = Counter()
        a = public_features(self.model, frame, work=work)
        b = public_features(self.model, changed, work=work)
        self.assertEqual(tuple(a.shape), (3, FEATURE_DIM))
        self.assertEqual(a.dtype, torch.float32)
        self.assertFalse(a.requires_grad)
        self.assertFalse(torch.equal(a, b))
        self.assertTrue(torch.equal(public_features(self.model, frame, draft_mode="masked"),
                                    public_features(self.model, changed, draft_mode="masked")))
        self.assertEqual(work["draft_pixel_encoder_panel_examples"], 12)

    def test_semantic_action_preserves_current_media_and_has_delayed_emission_effect(self):
        with torch.no_grad():
            self.model.semantic_cell[0].weight.zero_()
            self.model.semantic_cell[0].bias.fill_(2.)
        adaptive = initialize(self.model, self.observation,
                              generator=torch.Generator().manual_seed(14))
        clamped = initialize(self.model, self.observation,
                             generator=torch.Generator().manual_seed(14), shared_mode="clamped_initial")
        self.assertEqual(public_digest(public_frame(adaptive)), public_digest(public_frame(clamped)))
        rng_a, rng_c = torch.Generator().manual_seed(90), torch.Generator().manual_seed(90)
        before_rng = rng_a.get_state().clone()
        a = transition(self.model, adaptive, "refine_semantic", generator=rng_a)
        c = transition(self.model, clamped, "refine_semantic", generator=rng_c)
        self.assertTrue(torch.equal(rng_a.get_state(), before_rng))
        self.assertEqual(output_digests(a.pixels, a.tokens), output_digests(adaptive.pixels, adaptive.tokens))
        self.assertTrue(torch.equal(c.state.h, clamped.anchor_h))
        self.assertFalse(torch.equal(a.state.h, c.state.h))
        self.assertNotIn("emission_calls", a.ledger[-1]["work"])
        a = transition(self.model, a, "couple", generator=rng_a)
        c = transition(self.model, c, "couple", generator=rng_c)
        self.assertNotEqual(output_digests(a.pixels, a.tokens), output_digests(c.pixels, c.tokens))
        self.assertTrue(a.done and c.done)

    def test_partial_emissions_keep_old_modality_and_count_discarded_full_decoder_work(self):
        run = initialize(self.model, self.observation, generator=torch.Generator().manual_seed(6))
        for action, retained, discarded in (("refine_image", "tokens", "discarded_text_examples"),
                                             ("refine_text", "pixels", "discarded_image_examples")):
            child = transition(self.model, run, action, generator=torch.Generator().manual_seed(70))
            self.assertTrue(torch.equal(getattr(run, retained), getattr(child, retained)))
            work = child.ledger[-1]["work"]
            self.assertEqual(work["emission_calls"], 1)
            self.assertEqual(work["pixel_decoder_panel_examples"], 6)
            self.assertEqual(work["text_decoder_example_steps"], 21)
            self.assertEqual(work["sampled_bernoulli_variables"], 3 * 28 * 56)
            self.assertGreater(work["sampled_categorical_variables"], 0)
            self.assertEqual(work[discarded], 3)
        stopped = transition(self.model, run, "stop", generator=torch.Generator().manual_seed(70))
        self.assertEqual(stopped.ledger[-1]["work"], {})
        self.assertTrue(stopped.done)
        self.assertEqual(work_counts(stopped), work_counts(run))

    def test_policy_frame_cannot_mutate_owner_state_and_excludes_truth_and_future_rng(self):
        received = []
        def policy(frame):
            received.append(frame)
            self.assertEqual(tuple(field.name for field in fields(frame)),
                             ("state", "pixels", "tokens", "remaining"))
            self.assertEqual((frame.state.snapshot_digest, frame.state.source_digest), ("", ""))
            frame.pixels.zero_()
            frame.state.h.zero_()
            return "stop"
        a = rollout(self.model, self.observation, policy, generator=torch.Generator().manual_seed(99))
        b = rollout(self.model, self.observation, lambda frame: "stop",
                    generator=torch.Generator().manual_seed(99))
        self.assertEqual(output_digests(a.pixels, a.tokens), output_digests(b.pixels, b.tokens))
        self.assertTrue(torch.equal(a.state.h, b.state.h))
        truth = Target(self.observation.pixels, self.observation.text_tokens,
                       torch.zeros((3, 2), dtype=torch.long))
        with self.assertRaises(TypeError):
            initialize(self.model, truth, generator=torch.Generator())
        self.assertEqual(len(received), 1)

    def test_same_seed_replay_allocation_mask_and_context_intervention(self):
        def policy(frame):
            return "refine_image" if frame.remaining == 2 else "refine_text"
        a = rollout(self.model, self.observation, policy, generator=torch.Generator().manual_seed(88))
        b = rollout(self.model, self.observation, policy, generator=torch.Generator().manual_seed(88))
        self.assertEqual(a.ledger, b.ledger)
        self.assertEqual(work_counts(a)["state_transition_calls"], 4)
        self.assertEqual(work_counts(a)["emission_calls"], 3)
        allocation = initialize(self.model, self.observation, generator=torch.Generator().manual_seed(88),
                                 content_mode="allocation_only")
        self.assertEqual(feasible_mask(public_frame(allocation)).tolist(), [True, False, True, True, False])
        for action in ("refine_semantic", "couple"):
            with self.assertRaises(ValueError):
                transition(self.model, allocation, action, generator=torch.Generator())
        initial = initialize(self.model, self.observation, generator=torch.Generator().manual_seed(88),
                              context_mode="initial_only_context_intervention")
        self.assertEqual(float(initial.state.context.abs().sum()), 0.)
        self.assertFalse(initial.ledger[0]["matched_encoder_training_claim"])

    def test_fixed_action_training_and_no_grad_deployment_share_terminal_law(self):
        observation = observation_fixture(batch=4)
        def fixed_program():
            rng = torch.Generator().manual_seed(123)
            run = initialize(self.model, observation, generator=rng)
            image = transition(self.model, run, "refine_image", generator=rng)
            self.assertIs(image.text_log_probability, run.text_log_probability)
            final = transition(self.model, image, "refine_text", generator=rng)
            self.assertIs(final.image_log_probability, image.image_log_probability)
            return final
        trained = fixed_program()
        with torch.no_grad():
            deployed = fixed_program()
        self.assertEqual(trained.ledger, deployed.ledger)
        self.assertTrue(torch.equal(trained.pixels, deployed.pixels))
        self.assertTrue(torch.equal(trained.tokens, deployed.tokens))
        self.assertTrue(trained.terminal_log_probability.requires_grad)
        self.assertFalse(deployed.terminal_log_probability.requires_grad)
        losses = (.3 * trained.pixels.mean((1, 2, 3))
                  + .7 * ((trained.tokens[:, 1] % 5).float() / 4) - .5).reshape(2, 2)
        estimate = score_function_objective(trained.terminal_log_probability.reshape(2, 2),
                                             losses, risk_aversion=2.)
        estimate.surrogate.backward()
        for module in (self.model.pixel_encoder, self.model.semantic_cell,
                       self.model.pixel_decoder, self.model.text_decoder):
            self.assertGreater(sum(float(p.grad.abs().sum()) for p in module.parameters()
                                   if p.grad is not None), 0.)

    def test_failure_retains_action_commitment_without_claiming_completed_work(self):
        run = initialize(self.model, self.observation, generator=torch.Generator().manual_seed(4))
        with self.assertRaises(TransitionFailure) as caught:
            transition(self.model, run, "couple", generator=None)
        ledger = caught.exception.ledger
        self.assertEqual(ledger[-2]["phase"], "action_committed")
        self.assertEqual(ledger[-1]["phase"], "transition_failed")
        self.assertNotIn("work", ledger[-1])
        self.assertEqual(len(run.ledger), 1)


if __name__ == "__main__":
    unittest.main()
