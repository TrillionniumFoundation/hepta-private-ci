"""Mechanism-only tests, not new pretrained evidence or production acceptance."""
from __future__ import annotations

import unittest

import torch

from experiments.shared_stem_cell import selective_residual_governed as s


class SelectiveResidualTests(unittest.TestCase):
    def test_frozen_calibration_gates_unnecessary_training(self):
        self.assertEqual(s.selection_from_calibration(11, 12, 12), "shared")
        self.assertEqual(s.selection_from_calibration(11, 10, 11), "corrected")
        self.assertEqual(s.selection_from_calibration(11, 10, 10), "bank")
        self.assertEqual(s.selection_from_calibration(16, 16, 16), "shared")

    def test_missing_or_retyped_calibration_refuses(self):
        for value in (True, False, 1.0, -1, 17, None, "12"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                s.selection_from_calibration(value, 11, 10)
        with self.assertRaises(ValueError):
            s.selection_from_calibration(11, -1, 11)

    def test_shared_and_bank_head_are_separate_frozen_operators(self):
        torch.set_num_threads(1)
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(20261014)
            shared, bank, residual = (s.Head(386, "gated"),
                                      s.Head(384, "gated"), s.Head(384, "linear"))
        shared.eval().requires_grad_(False)
        bank.eval().requires_grad_(False)
        with torch.no_grad():
            residual.base.weight.zero_()
            residual.base.bias.zero_()
        x = torch.randn(4, 384)
        routes = torch.tensor([0, 1, 1, 0])
        one_hot = torch.nn.functional.one_hot(routes, 2).float()
        before = {k: v.clone() for k, v in shared.state_dict().items()}
        result = shared(torch.cat([x, one_hot], -1)) + residual(x)
        self.assertEqual(result.shape, (4, 4))
        self.assertEqual(sum(p.numel() for p in shared.parameters()), 6224)
        self.assertEqual(sum(p.numel() for p in residual.parameters()), 1540)
        self.assertEqual(sum(p.numel() for p in bank.parameters()), 6192)
        self.assertTrue(all(torch.equal(old, shared.state_dict()[k])
                            for k, old in before.items()))


if __name__ == "__main__":
    unittest.main()
