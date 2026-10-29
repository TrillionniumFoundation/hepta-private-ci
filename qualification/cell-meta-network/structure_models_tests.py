"""Behavior and persistence checks for actual differentiable structures."""

from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "memory-cell-adapters"))

from structure_models import ARMS, Structure, fit
from tensor_cell import CellConfig, OutputSpec, TensorCell


class StructureTests(unittest.TestCase):
    def test_initial_behavior_and_restore_preserve_the_same_parent(self):
        torch.set_num_threads(1)
        parent = TensorCell(CellConfig("parent", rank=2, input_dim=8,
                                      outputs=(OutputSpec("bits", "binary", 4),), seed=37), "a" * 64)
        x = torch.eye(8)
        target = torch.tensor([[i % 2, (i // 2) % 2, 1, 0] for i in range(8)], dtype=torch.float32)
        parent.fit(x.numpy(), target.numpy(), source_ids=[str(i) for i in range(8)],
                   steps=40, batch_size=8, seed=37)
        expected = parent(x).detach()
        counts = []
        for arm in ARMS:
            structure = Structure(parent, arm)
            counts.append(structure.counts())
            torch.testing.assert_close(structure(x, torch.arange(8)), expected, rtol=0, atol=1e-6)
            with tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "checkpoint"
                structure.save(path)
                restored = Structure.load(path, "a" * 64)
                torch.testing.assert_close(restored(x, torch.arange(8)), structure(x, torch.arange(8)),
                                           rtol=0, atol=0)
                self.assertEqual(restored.counts(), structure.counts())
        self.assertEqual(counts, [counts[0]] * len(ARMS))

    def test_all_arms_update_from_the_same_minibatches(self):
        torch.set_num_threads(1)
        x = torch.eye(8)
        y = torch.tensor([[i % 2, (i // 2) % 2, 1, 0] for i in range(8)], dtype=torch.float32)
        parent = TensorCell(CellConfig("parent", rank=2, input_dim=8,
                                      outputs=(OutputSpec("bits", "binary", 4),), seed=11), "b" * 64)
        receipts = []
        for arm in ARMS:
            model = Structure(parent, arm)
            before = model(x, torch.arange(8)).detach().clone()
            model.propose_routes(x, y, torch.arange(8))
            receipts.append(fit(model, x, y, torch.arange(8), seed=19, steps=50,
                                batch_size=8, learning_rate=0.01))
            self.assertFalse(torch.equal(before, model(x, torch.arange(8)).detach()))
        self.assertEqual(len({r["sample_schedule_sha256"] for r in receipts}), 1)


if __name__ == "__main__":
    unittest.main()
