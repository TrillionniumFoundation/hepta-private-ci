"""Toy numerical gate; invoke only after source/resource freeze, before fit."""
import unittest

import torch

from .joint import build, changes, restore, state, state_digest
from .joint_program import apply_program
from .tasks import generate
from .environment import execution_identity


class JointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        execution_identity()

    def test_roundtrip_and_actual_outer_gradient(self):
        torch.manual_seed(71)
        model = build("first_passage")
        data = generate("unit-test-only/joint-gradient", 71, "first_passage", "train", 2, 4)
        initial = state(model)
        loss = (model(data) - torch.from_numpy(data["y"])).square().mean()
        loss.backward()
        gradients = {name: p.grad for name, p in model.named_parameters() if p.requires_grad}
        self.assertEqual(set(gradients), set(model.mask))
        self.assertTrue(all(g is not None and torch.isfinite(g).all() for g in gradients.values()))
        self.assertTrue(any(g.abs().max() > 0 for name, g in gradients.items() if name.startswith("flow.")))
        restore(model, initial)
        self.assertEqual(state_digest(initial), state_digest(state(model)))

    def test_semantic_edit_stays_in_mask_and_guard_rejects_other_edit(self):
        model = build("association")
        initial = state(model)
        apply_program(model, "association")
        self.assertTrue(changes(initial, model))
        with torch.no_grad():
            model.flow.predictor.weight.add_(1)
        with self.assertRaisesRegex(ValueError, "outside"):
            changes(initial, model)


if __name__ == "__main__":
    unittest.main()

