import hashlib
from pathlib import Path
import tempfile
import unittest

import numpy as np

from hepta_cells.plastic_bank import PlasticBank


class PlasticBankTests(unittest.TestCase):
    def setUp(self):
        self.x = np.random.default_rng(33).normal(size=(12, 4))
        self.y = self.x[:, :1]

    def test_shared_interference_and_private_isolation(self):
        for arm in ("shared_plastic", "frozen_backbone", "independent"):
            bank = PlasticBank(arm, 4, 2, ["A", "B"])
            bank, _ = bank.propose("A", self.x, self.y, updates=8)
            before = bank.head("A").predict(self.x)
            candidate, receipt = bank.propose(
                "B", self.x, -self.y, updates=8
            )
            after = candidate.head("A").predict(self.x)
            if arm == "shared_plastic":
                self.assertGreater(np.max(np.abs(after - before)), 1e-8)
            else:
                np.testing.assert_array_equal(after, before)
            np.testing.assert_array_equal(
                bank.head("A").predict(self.x), before
            )
            self.assertEqual(receipt["completed_updates"], 8)

    def test_shared_gradient_finite_difference(self):
        bank = PlasticBank("shared_plastic", 4, 2, ["A", "B"])
        bank, _ = bank.propose("A", self.x, self.y, updates=2)
        rate, eps = 1e-4, 1e-6
        candidate, _ = bank.propose(
            "A", self.x, self.y, learning_rate=rate
        )
        analytic = (bank.first - candidate.first) / rate
        for index in np.ndindex(bank.first.shape):
            original = bank.first[index]
            bank.first[index] = original + eps
            upper = np.mean((bank.head("A").predict(self.x) - self.y)**2)
            bank.first[index] = original - eps
            lower = np.mean((bank.head("A").predict(self.x) - self.y)**2)
            bank.first[index] = original
            self.assertAlmostEqual(
                analytic[index], (upper - lower) / (2 * eps), places=8
            )

    def test_resume_next_update_and_plan(self):
        bank = PlasticBank("shared_plastic", 4, 2, ["A", "B"])
        bank, _ = bank.propose("A", self.x, self.y, updates=3)
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "checkpoint.npz"
            pin = bank.checkpoint(path, cursor=3, plan_sha256="a" * 64)
            restored, cursor = PlasticBank.restore(
                path, expected_sha256=pin, plan_sha256="a" * 64
            )
            self.assertEqual((restored.digest, cursor), (bank.digest, 3))
            left, _ = bank.propose("B", self.x, -self.y)
            right, _ = restored.propose("B", self.x, -self.y)
            self.assertEqual(left.digest, right.digest)
            with self.assertRaises(ValueError):
                PlasticBank.restore(
                    path, expected_sha256=pin, plan_sha256="b" * 64
                )

    def test_failed_attempt_retains_receipt(self):
        bank = PlasticBank("shared_plastic", 4, 2, ["A", "B"])
        pin = bank.digest
        with self.assertRaises(ValueError) as error:
            bank.propose("A", self.x, self.y, learning_rate=-1)
        self.assertEqual(error.exception.receipt["status"], "failed")
        self.assertIn("wall_ns", error.exception.receipt)
        self.assertEqual(bank.digest, pin)

    def test_nonfinite_loss_charges_attempted_work(self):
        bank = PlasticBank("shared_plastic", 4, 2, ["A", "B"])
        with np.errstate(over="ignore", invalid="ignore"):
            with self.assertRaises(FloatingPointError) as error:
                bank.propose(
                    "A", np.ones((2, 4)), np.full((2, 1), 1e200),
                    learning_rate=1e-300,
                )
        receipt = error.exception.receipt
        self.assertEqual(
            (receipt["status"], receipt["attempted_updates"],
             receipt["completed_updates"]), ("failed", 1, 0),
        )
        self.assertEqual(receipt["forward_mac"], 20)
        self.assertEqual(receipt["gradient_mac"], 0)

    def test_restore_cursor_bound(self):
        bank = PlasticBank("shared_plastic", 4, 2, ["A", "B"])
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "checkpoint.npz"
            bank.checkpoint(path, cursor=1, plan_sha256="a" * 64)
            with np.load(path, allow_pickle=False) as archive:
                payload = {key: archive[key] for key in archive.files}
            payload["cursor"] = np.asarray(2**63, dtype=np.uint64)
            np.savez_compressed(path, **payload)
            pin = hashlib.sha256(path.read_bytes()).hexdigest()
            with self.assertRaises(ValueError):
                PlasticBank.restore(
                    path, expected_sha256=pin, plan_sha256="a" * 64
                )


if __name__ == "__main__":
    unittest.main()
