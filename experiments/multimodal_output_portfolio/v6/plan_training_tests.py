"""Finite NDU gradient and deployed content-plan boundary tests."""

from pathlib import Path
import tempfile
import unittest

import torch
from torch import nn

from .data import Observation, SourceCorpus, SourceSplit, Target
from .neural import NeuralPortfolio, NeuralSnapshot
from .plan_training import ControlledSnapshot, PLANS, PlanHead, finite_ndu_loss, fit_plan_head


class ExactPlanGradientTests(unittest.TestCase):
    def test_gradient_matches_exact_probability_derivative_and_detaches_rewards(self):
        logits = torch.tensor([[.2, -.1, .8, 0.]], dtype=torch.float64, requires_grad=True)
        rewards = torch.tensor([[[.9, -.9], [-.1, -.1], [.3, .4], [-.6, .1]]],
                               dtype=torch.float64, requires_grad=True)
        gamma = 1.7
        finite_ndu_loss(logits, rewards, gamma).sum().backward()
        probabilities = logits.detach().softmax(1)
        scenario_weights = (-gamma * rewards.detach()).exp().mean(2)
        normalized = probabilities * scenario_weights
        exact = (normalized / normalized.sum(1, keepdim=True) - probabilities) / gamma
        self.assertTrue(torch.allclose(logits.grad, exact, atol=1e-12, rtol=1e-12))
        self.assertIsNone(rewards.grad)

    def test_entropic_control_distinguishes_tail_risk_from_mean(self):
        rewards = torch.tensor([[[.9, -.7], [0., 0.], [-1., -1.], [-1., -1.]]])
        self.assertEqual(int(rewards.mean(2).argmax(1)), 0)
        logits = torch.zeros(1, 4, requires_grad=True)
        finite_ndu_loss(logits, rewards, 2.).sum().backward()
        self.assertLess(float(logits.grad[0, 1]), float(logits.grad[0, 0]))


class ControlledBoundaryTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(2)
        torch.manual_seed(77)
        self.base = NeuralSnapshot(NeuralPortfolio(hidden=16))
        gate = PlanHead(16)
        with torch.no_grad():
            gate.net[-1].weight.zero_()
            gate.net[-1].bias[:] = torch.tensor([4., 0., 0., 0.])
        self.snapshot = ControlledSnapshot(self.base, gate)
        self.observation = Observation(
            torch.rand(2, 1, 28, 56), torch.ones(2, 1, 28, 56),
            torch.tensor([[1, 9, 12, 11, 13, 11, 2, 0]]).repeat(2, 1),
        )

    def test_gate_executes_actual_plan_and_preserves_observation_identity(self):
        state = self.snapshot.encode(self.observation, noise_seed=19)
        expected = self.base.encode(self.observation, noise_seed=19)
        for action in PLANS[0]:
            expected = self.base.step(expected, action)
        self.assertTrue(torch.equal(self.snapshot.decode(state).image_logits,
                                    self.base.decode(expected).image_logits))
        self.assertEqual(state.plan_indices, (0, 0))
        changed = self.snapshot.step(state, "refine_semantic")
        self.assertEqual(self.snapshot.observation_identity(state),
                         self.snapshot.observation_identity(changed))
        self.assertNotEqual(self.snapshot.state_key(state), self.snapshot.state_key(changed))
        target = Target(self.observation.pixels, self.observation.text_tokens,
                        torch.zeros(2, 2, dtype=torch.long))
        with self.assertRaises(TypeError):
            self.snapshot.encode(target)

    def test_single_file_roundtrip_and_gate_integrity(self):
        expected = self.snapshot.decode(self.snapshot.encode(self.observation))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "controlled.pt"
            self.snapshot.save(path)
            restored = ControlledSnapshot.load(path)
            actual = restored.decode(restored.encode(self.observation))
        self.assertEqual(restored.fingerprint, self.snapshot.fingerprint)
        self.assertTrue(torch.equal(actual.token_ids, expected.token_ids))
        self.assertTrue(torch.equal(actual.image_logits, expected.image_logits))
        with torch.no_grad():
            next(restored._gate.parameters()).add_(1)
        with self.assertRaises(RuntimeError):
            restored.verify_integrity()

    def test_allocation_ablation_disables_shared_controls_including_initial_plan(self):
        initial = self.base.encode(self.observation, noise_seed=19, content_control=False)
        state = self.snapshot.encode(self.observation, noise_seed=19, content_control=False)
        self.assertEqual(state.plan_indices, (-1, -1))
        self.assertTrue(torch.equal(state.neural.h, initial.h))
        for action in ("refine_image", "refine_text", "refine_text", "refine_image"):
            state = self.snapshot.step(state, action)
            self.assertTrue(torch.equal(state.neural.h, initial.h))
        for action in ("refine_semantic", "couple"):
            with self.assertRaises(ValueError):
                self.snapshot.step(state, action)
        with self.assertRaises(TypeError):
            self.snapshot.encode(self.observation, content_control="false")

    def test_real_decode_training_has_matched_initialization_and_no_runtime_reward_table(self):
        # Fixtures exercise the protocol; they are never research evidence.
        images = (torch.rand(16, 1, 28, 28) * 255).to(torch.uint8)
        source = SourceSplit(images, torch.arange(16) % 10,
                             tuple(f"fixture:{i}" for i in range(16)),
                             tuple(f"fixture-hash:{i}" for i in range(16)))
        corpus = SourceCorpus({"train": source}, {"manifest_sha256": "fixture"})
        observer = nn.Sequential(nn.Flatten(), nn.Linear(784, 10)).eval().requires_grad_(False)
        records = []
        for profile in ("supervised", "terminal_entropic_ndu"):
            snapshot, report = fit_plan_head(self.base, corpus, observer, profile, 13,
                                              fit_pairs=4, steps=3)
            self.assertGreater(report["gate_gradient_abs_sum_max"], 0.)
            self.assertTrue(report["training_reward_is_independent_emitted_output_score"])
            self.assertNotIn("utility_table", snapshot.__dict__)
            self.assertNotIn("observer", snapshot.__dict__)
            records.append(report)
        for key in ("initial_gate_sha256", "gate_update_schedule_sha256",
                    "source_ids_sha256", "output_observation_sha256", "utility_table"):
            self.assertEqual(records[0][key], records[1][key])


if __name__ == "__main__":
    unittest.main()
