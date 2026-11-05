"""Numerical adapter and geometry tests, without model capability claims."""

import copy
import unittest

import numpy as np
import torch
from torch.nn import functional as F

from cells import FourCells, apply_constraints, state_features, token_roles


class CellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.threads = torch.get_num_threads()
        torch.set_num_threads(1)

    @classmethod
    def tearDownClass(cls):
        torch.set_num_threads(cls.threads)

    def setUp(self):
        torch.manual_seed(7)
        self.model = FourCells(8, list(range(8)), [2, 3, 4, 5], [6, 7], rank=8)

    def test_sparse_training_matches_full_vocabulary_softmax(self):
        hidden = torch.randn(24, 8)
        full = torch.randn(24, 12) * 2
        ids = torch.tensor([0, 2, 3, 7] * 6)
        roles = torch.tensor([0, 1, 2, 3] * 6)
        with torch.no_grad():
            for cell in self.model.cells:
                cell.up.bias.copy_(torch.linspace(-1, 1, len(cell.up.bias)))
            corrections = self.model.corrections(hidden)
            expected = []
            for cell in range(4):
                mask = torch.ones(24, dtype=torch.bool) if cell == 3 else roles == cell
                adjusted = full[mask].clone()
                adjusted[:, :8] += corrections[mask, cell]
                expected.append(F.cross_entropy(adjusted, ids[mask])
                                + 0.002 * corrections[mask, cell].square().mean())
        bank = {"hidden": hidden.numpy(), "logits": full[:, :8].numpy(),
                "full_logsumexp": torch.logsumexp(full.double(), -1).numpy(),
                "target_ids": ids.numpy(), "roles": roles.numpy()}
        before = copy.deepcopy(bank)
        report = self.model.fit(bank, epochs=1, learning_rate=0)
        self.assertAlmostEqual(report["losses"][0], float(torch.stack(expected).mean()), places=5)
        for key in bank:
            np.testing.assert_array_equal(bank[key], before[key])

    def test_training_reduces_loss_and_changes_all_four_cells(self):
        ids = np.tile(np.arange(8), 8)
        bank = {"hidden": np.eye(8, dtype=np.float32)[ids],
                "logits": np.zeros((64, 8), dtype=np.float32),
                "full_logsumexp": np.full(64, np.log(12), dtype=np.float32),
                "target_ids": ids, "roles": np.tile([0, 0, 1, 1, 2, 2, 3, 3], 8)}
        report = self.model.fit(bank, epochs=24, learning_rate=0.05)
        self.assertLess(report["losses"][-1], 0.8 * report["losses"][0])
        self.assertTrue(all(bool(cell.up.weight.abs().max() > 0) for cell in self.model.cells))
        self.assertFalse(self.model.training)

    def test_fixed_weights_are_stable_and_changed_weights_change_logits(self):
        with torch.no_grad():
            self.model.cells[0].up.bias[0] = 2
            self.model.cells[1].up.bias[0] = 2
        hidden = torch.zeros(8)
        fixed, _ = self.model.delta(hidden, [1, 0, 0, 0], 12)
        repeated, _ = self.model.delta(hidden, [1, 0, 0, 0], 12)
        dynamic, _ = self.model.delta(hidden, [0, 1, 0, 0], 12)
        self.assertTrue(torch.equal(fixed, repeated))
        self.assertEqual((int(fixed.argmax()), int(dynamic.argmax())), (0, 2))
        self.assertTrue(torch.equal(dynamic[8:], torch.zeros(4)))
        with torch.no_grad():
            for cell in self.model.cells:
                cell.up.bias.fill_(1000)
        bounded, corrections = self.model.delta(hidden, [0.1, 0.2, 0.3, 0.4], 12)
        self.assertLessEqual(float(corrections.detach().abs().max()), 3)
        self.assertLessEqual(float(bounded.detach().abs().max()), 3)

    def test_features_handle_masked_logits_and_ignore_unseen_references(self):
        state = {"logits": torch.tensor([0., float("-inf"), 1., 2., 3., 4., 1., 0., 2., 1., 0., 3.]),
                 "step": 4, "remaining_seconds": 10., "token_ids": [0, 2, 3]}
        correction = self.model.corrections(torch.zeros(8))
        features, covariance = state_features(state, correction, list(range(8)), [2, 3, 4, 5], 7)
        self.assertTrue(np.isfinite(features).all())
        changed = dict(state, reference={"boxes": [[0, 0, 1, 1]], "label": "wrong"})
        other, _ = state_features(changed, correction, list(range(8)), [2, 3, 4, 5], 7)
        np.testing.assert_array_equal(features, other)
        self.assertTrue(torch.isfinite(covariance).all())

    def test_covariance_matches_full_distribution_centered_moments(self):
        logits, correction = torch.randn(12), torch.randn(4, 8)
        state = {"logits": logits, "step": 0, "remaining_seconds": 5, "token_ids": []}
        _, covariance = state_features(state, correction, list(range(8)), [2, 3, 4, 5], 7)
        expanded = torch.cat((correction, torch.zeros(4, 4)), dim=-1)
        probability = logits.softmax(-1)
        centered = expanded - (expanded * probability).sum(-1, keepdim=True)
        expected = (centered[:, None] * centered[None, :] * probability).sum(-1)
        torch.testing.assert_close(covariance, expected)
        self.assertGreaterEqual(float(torch.linalg.eigvalsh(covariance).min()), -1e-6)

    def test_constraints_preserve_feasible_positive_area_boxes(self):
        locations, eos = [2, 3, 4, 5], 7
        logits = torch.zeros(12)
        opening = apply_constraints(logits, [], locations, eos)
        self.assertTrue(torch.isneginf(opening[locations[-1]]))
        y1 = apply_constraints(logits, [3], locations, eos)
        self.assertTrue(torch.isneginf(y1[[0, 1, 5, 6, 7]]).all())
        x2 = apply_constraints(logits, [3, 2], locations, eos)
        self.assertTrue(torch.isneginf(x2[[0, 1, 2, 3, 6, 7]]).all())
        self.assertTrue(torch.isfinite(x2[[4, 5]]).all())
        y2 = apply_constraints(logits, [3, 2, 4], locations, eos)
        self.assertTrue(torch.isneginf(y2[2]))
        self.assertTrue(torch.isfinite(y2[[3, 4, 5]]).all())
        with self.assertRaises(ValueError):
            apply_constraints(logits, [5, 2], locations, eos)
        self.assertEqual(token_roles([0, 2, 3, 4, 5, 7], locations, [6, 7]), [0, 1, 2, 1, 2, 3])


if __name__ == "__main__":
    unittest.main()
