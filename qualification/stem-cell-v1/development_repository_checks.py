"""Require actual repository fitter/factory, not substituted fixture functions."""

import unittest

import torch
from torch.nn import functional as F

from model_runner import build_head, train_head
from development_tensors import BasisCellHeads, fit_cell_candidate, parameter_digest
from development_trial import train_shared_head_trial
from shared_encoder_batch import SharedStemEngine
from test_shared_encoder_eviction import ToyBackend, request


class ExistingOwnerEntryPoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.threads = torch.get_num_threads()
        torch.set_num_threads(1)

    @classmethod
    def tearDownClass(cls):
        torch.set_num_threads(cls.threads)

    def test_actual_registered_factory_and_fitter(self):
        engine = SharedStemEngine(ToyBackend())
        items = tuple(request("short" if i % 2 else "a much longer source", str(i)) for i in range(40))
        labels = {str(i): i % 2 for i in range(24)}
        frozen, trained, report = train_shared_head_trial(engine, items, labels, classes=2,
            head_kind="film", parameter_budget=64, steps=100, seed=3)
        self.assertEqual(report["physical_encoder_calls"], 1)
        self.assertNotEqual(parameter_digest(frozen["cell"]), parameter_digest(trained["cell"]))
        self.assertEqual(len(report["predictions"]), 16)
        self.assertTrue(report["simulated_encoder"])
        self.assertFalse(report["production_authorized"])

    def test_actual_adamw_keeps_peer_rows_and_frozen_bank_unchanged(self):
        bank = BasisCellHeads(4, 2, 4, ("one", "two"), seed=4)
        with torch.no_grad():
            bank.coefficients[1].fill_(.9)
        x = torch.randn(32, 4, generator=torch.Generator().manual_seed(4))
        y, ids = (x[:, 0] > 0).long(), torch.zeros(32, dtype=torch.long)
        original = parameter_digest(bank)
        old_loss = F.cross_entropy(bank(x, ids), y).item()
        candidate, _ = fit_cell_candidate(bank, "one", x, y, fit=train_head, steps=500, seed=9)
        self.assertEqual(parameter_digest(bank), original)
        self.assertTrue(torch.equal(candidate.coefficients[1], bank.coefficients[1]))
        self.assertLess(F.cross_entropy(candidate(x, ids), y).item(), old_loss)

    def test_existing_factory_physical_parameter_budget_still_applies(self):
        with self.assertRaises(ValueError):
            build_head(torch, 512, 128, "linear", 2048)


if __name__ == "__main__":
    unittest.main()
