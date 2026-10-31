"""Behavioral tests for trained parameters, portable execution and continuation."""

import unittest

import numpy as np

from learned import MLP, features, predict_export, train_mlp


class LearnedTests(unittest.TestCase):
    def test_trained_hidden_weights_and_independent_reader(self):
        rng = np.random.default_rng(112)
        x = rng.normal(size=(24, 12)).astype(np.float32)
        x /= np.linalg.norm(x, axis=1, keepdims=True)
        y = rng.integers(0, 2, size=(24, 12)).astype(np.float32)
        model = train_mlp(x, y, hidden=32, steps=600, seed=77)
        np.testing.assert_array_equal(model.predict(x) > 0, y > 0)
        self.assertTrue(all(v > 0 for v in model.receipt["parameter_change_norm"].values()))
        payload = model.export()
        np.testing.assert_allclose(predict_export(payload, x), model.predict(x), atol=1e-5, rtol=1e-5)
        restored = MLP.from_export(payload)
        np.testing.assert_array_equal(restored.predict(x), model.predict(x))
        payload["arrays"]["hidden.weight"]["f32le_hex"] = "00" + payload["arrays"]["hidden.weight"]["f32le_hex"][2:]
        with self.assertRaisesRegex(ValueError, "identity"):
            MLP.from_export(payload)

    def test_persistent_optimizer_continuation(self):
        x = features(["alpha beta", "gamma delta", "alpha gamma", "delta beta"], 16)
        y = np.array([[1, 0], [0, 1], [1, 1], [0, 0]], dtype=np.float32)
        model = train_mlp(x, y, hidden=8, steps=40, seed=9)
        restored = MLP.from_export(model.export(include_optimizer=True))
        a = train_mlp(x, y, hidden=8, steps=50, seed=11, initial=model)
        b = train_mlp(x, y, hidden=8, steps=50, seed=11, initial=restored)
        self.assertEqual(a.export()["parameter_sha256"], b.export()["parameter_sha256"])
        self.assertEqual(a.receipt["initial_optimizer_step"], 40)
        self.assertEqual(a.receipt["optimizer_step"], 90)


if __name__ == "__main__":
    unittest.main()
