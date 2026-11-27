"""Gradient, actual learning and immutable artifact identity checks."""

import tempfile
import unittest
from pathlib import Path

import numpy as np

from cell_learning_models import NumpyCellHead, normalize_features


class LearningModelTests(unittest.TestCase):
    def test_analytic_gradients_against_finite_difference(self):
        rng = np.random.default_rng(4)
        x = normalize_features(rng.normal(size=(7, 3)))
        y = np.array([0, 1, 0, 1, 0, 1, 1])
        for mode in ("linear", "gated", "residual"):
            head = NumpyCellHead(3, 2, mode, rank=2)
            if mode == "residual":
                head.params["U"][:] = rng.normal(0, .1, head.U.shape)
            _, gradient = head.loss_gradients(x, y, .03)
            for name, value in head.params.items():
                for index in np.ndindex(value.shape):
                    old, step = value[index], 1e-5
                    value[index] = old + step
                    high, _ = head.loss_gradients(x, y, .03)
                    value[index] = old - step
                    low, _ = head.loss_gradients(x, y, .03)
                    value[index] = old
                    with self.subTest(mode=mode, name=name, index=index):
                        self.assertAlmostEqual((high - low) / (2 * step), gradient[name][index], places=6)

    def test_every_arm_really_learns_without_changing_features(self):
        rng = np.random.default_rng(11)
        x = rng.normal(size=(32, 8))
        y = (x[:, 0] > 0).astype(np.int64)
        original = x.copy()
        for mode in ("linear", "gated", "residual"):
            head = NumpyCellHead(8, 2, mode, rank=2)
            result = head.train(x, y, steps=100)
            self.assertLess(result["final_loss"], result["initial_loss"])
            self.assertNotEqual(result["initial_tensor_sha256"], result["trained_tensor_sha256"])
            self.assertGreaterEqual(float((head.predict_logits(x).argmax(axis=1) == y).mean()), .9)
            self.assertEqual(result["example_updates"], 3200)
        np.testing.assert_array_equal(original, x)

    def test_portable_round_trip_and_tamper_rejection(self):
        x = np.eye(3)
        head = NumpyCellHead(3, 2, "residual", rank=2)
        self.assertIsNone(head.feature_identity)
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "head"
            head.save(target, {"encoder": "frozen-v1"})
            restored = NumpyCellHead.load(target, {"encoder": "frozen-v1"})
            self.assertEqual(head.feature_identity, {"encoder": "frozen-v1"})
            self.assertEqual(restored.feature_identity, head.feature_identity)
            np.testing.assert_array_equal(restored.predict_logits(x), head.predict_logits(x))
            with self.assertRaises(ValueError):
                NumpyCellHead.load(target, {"encoder": "frozen-v2"})
            with (target / "weights.npz").open("ab") as stream:
                stream.write(b"changed")
            with self.assertRaises(ValueError):
                NumpyCellHead.load(target, {"encoder": "frozen-v1"})

    def test_budgets_and_bad_training_reject(self):
        with self.assertRaises(ValueError):
            NumpyCellHead(768, 64, "residual", max_parameters=1000)
        head = NumpyCellHead(3, 2)
        for y in ([True, False, True], [0, 0, 0], [0, 1, 2]):
            with self.assertRaises(ValueError):
                head.train(np.eye(3), y)
        with self.assertRaises(ValueError):
            head.predict_logits(np.full((1, 3), np.nan))


if __name__ == "__main__":
    unittest.main()
