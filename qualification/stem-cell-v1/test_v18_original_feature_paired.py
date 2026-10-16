"""Source-only V18 physical Head anti-bypass and zero-delta tests."""
import tempfile
import unittest
from pathlib import Path

import numpy as np
import torch

from v18_original_feature_paired import (
    ARMS, OutputResidual, centers_from_train, check, digest, metric, original_inputs,
)


class Tests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)

    def test_original_sha256(self):
        self.assertEqual(digest(b"abc"), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")

    def test_denied_gate(self):
        with self.assertRaises(ValueError):
            check(False, "denied")

    def test_missing_material(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises((ValueError, FileNotFoundError)):
                original_inputs(d)

    def test_unpinned_material(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "input.json").write_text("{}")
            (Path(d) / "features.safetensors").write_bytes(b"fabrication")
            with self.assertRaises(ValueError):
                original_inputs(d)

    def test_zero_delta(self):
        x = torch.linspace(-1, 1, 384).repeat(6, 1)
        for mode in ("linear", "gated_residual", "split_router"):
            head = OutputResidual(mode)
            route = torch.tensor([0, 1, 0, 1, 0, 1]) if mode == "split_router" else None
            self.assertTrue(torch.equal(head(x, route), torch.zeros(6, 4)))

    def test_required_split_route(self):
        with self.assertRaises(ValueError):
            OutputResidual("split_router")(torch.zeros(2, 384))

    def test_parameter_census(self):
        for mode, expected in (("linear", 1540), ("gated_residual", 1925), ("split_router", 3080)):
            self.assertEqual(sum(p.numel() for p in OutputResidual(mode).parameters()), expected)

    def test_train_only_center_is_deterministic(self):
        x = torch.zeros(64, 384)
        x[1::2, 0] = 3
        self.assertTrue(torch.equal(centers_from_train(x), centers_from_train(x)))

    def test_four_class_uniform_brier(self):
        score = metric(torch.zeros(2, 4), torch.tensor([0, 1]))
        self.assertEqual(score["multiclass_brier"], 0.75)
        self.assertEqual(score["accuracy"], 0.5)

    def test_required_arms(self):
        self.assertEqual(set(ARMS), {"no_change", "linear", "gated_residual", "continued_single", "split_router"})

    def test_same_snapshot_cannot_claim_learning(self):
        x = torch.randn(3, 384, generator=torch.Generator().manual_seed(41))
        parent = torch.zeros(3, 4)
        for mode in ("linear", "gated_residual", "split_router"):
            head = OutputResidual(mode)
            route = torch.zeros(3, dtype=torch.long) if mode == "split_router" else None
            self.assertTrue(torch.equal(parent + head(x, route), parent))


if __name__ == "__main__":
    unittest.main()
