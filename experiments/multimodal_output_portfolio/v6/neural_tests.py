"""Behavioral tests for neural controls and immutable inference snapshots."""

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

import torch

from .data import Observation, Target
from .neural import ACTIONS, NeuralPortfolio, NeuralSnapshot


class NeuralBoundaryTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(2)
        torch.manual_seed(11)
        self.model = NeuralPortfolio(hidden=32)
        self.observation = Observation(
            torch.rand(2, 1, 28, 56), torch.ones(2, 1, 28, 56),
            torch.tensor([[1, 9, 12, 11, 13, 11, 2, 0]]).repeat(2, 1),
        )
        self.snapshot = NeuralSnapshot(self.model)

    def test_controls_change_content_without_mutating_input_state(self):
        state = self.snapshot.encode(self.observation)
        before_key = self.snapshot.state_key(state)
        before_output = self.snapshot.decode(state)
        for action in ACTIONS:
            with self.subTest(action=action):
                updated = self.snapshot.step(state, action)
                output = self.snapshot.decode(updated)
                self.assertEqual(before_key, self.snapshot.state_key(state))
                self.assertNotEqual(before_key, self.snapshot.state_key(updated))
                if action in {"refine_image", "refine_text"}:
                    self.assertTrue(torch.equal(updated.h, state.h))
                else:
                    self.assertFalse(torch.equal(updated.h, state.h))
                relevant = output.text_logits if action == "refine_text" else output.image_logits
                previous = before_output.text_logits if action == "refine_text" else before_output.image_logits
                self.assertFalse(torch.equal(relevant, previous))

    def test_foreign_state_and_target_are_rejected(self):
        target = Target(self.observation.pixels, self.observation.text_tokens,
                        torch.zeros(2, 2, dtype=torch.long))
        with self.assertRaises(TypeError):
            self.snapshot.encode(target)
        state = self.snapshot.encode(self.observation)
        with self.assertRaises(ValueError):
            self.snapshot.decode(replace(state, snapshot_digest="different-weights"))

    def test_snapshot_is_independent_and_serialization_preserves_outputs(self):
        state = self.snapshot.encode(self.observation)
        expected = self.snapshot.decode(state)
        with torch.no_grad():
            next(self.model.parameters()).add_(1)
        self.snapshot.verify_integrity()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.pt"
            self.snapshot.save(path)
            restored = NeuralSnapshot.load(path)
            actual = restored.decode(restored.encode(self.observation))
        self.assertEqual(self.snapshot.fingerprint, restored.fingerprint)
        for field in ("image_logits", "text_logits", "token_ids", "digit_logits"):
            self.assertTrue(torch.equal(getattr(expected, field), getattr(actual, field)))

    def test_explicit_parameter_mutation_is_detected(self):
        with torch.no_grad():
            next(self.snapshot._model.parameters()).add_(1)
        with self.assertRaises(RuntimeError):
            self.snapshot.verify_integrity()


if __name__ == "__main__":
    unittest.main()
