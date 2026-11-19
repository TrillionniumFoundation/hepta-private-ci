"""Hand-made kernels and entry inventory only; no retained-model outcomes."""

import unittest

import numpy as np

from data import templates
from independent.accounting import WorkLedger
from model import JointModel
from ndu_training.reinfer_d1.kernels import Reference, planned_units, request_readout
from ndu_training.reinfer_d1.service import WILLIAMS


class EntryTests(unittest.TestCase):
    def test_hand_reference_mean_and_exact_request_reward(self):
        rng = np.random.default_rng(42)
        model = JointModel(202, 12, 192, hidden=3)
        pixels = np.clip(templates(), 0.001, 0.999)
        model.params["decoder"] = np.log(pixels / (1 - pixels))
        model.params["decoder_bias"][:] = 0
        x = rng.normal(0, 0.1, (8, 202))
        y = np.arange(8)
        ledger = WorkLedger("hand")
        reference = Reference(model, x, y, ledger)
        self.assertLess(reference.mean_max_error, 1e-12)
        result = request_readout(reference.p, reference.q, y, reference, ledger)
        np.testing.assert_allclose(
            result["task_utility"],
            result["reward_components"].sum(1),
            rtol=0,
            atol=1e-12,
        )
        self.assertTrue(np.all(result["Z"] > 0))
        self.assertNotIn("optimizer_updates", ledger.totals)

    def test_complete_quota_and_balanced_order(self):
        quote = planned_units()
        self.assertEqual(12 * 48 * 4 * 64, 147456)
        self.assertTrue(
            all(value < 4_000_000_000 for value in quote["total_each_arm"].values())
        )
        pairs = [(row[i], row[i + 1]) for row in WILLIAMS for i in range(3)]
        self.assertEqual(len(set(pairs)), 12)
        for column in range(4):
            self.assertEqual(set(row[column] for row in WILLIAMS), set(range(4)))


if __name__ == "__main__":
    unittest.main()
