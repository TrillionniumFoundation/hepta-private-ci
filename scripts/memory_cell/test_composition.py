import unittest

import numpy as np
import torch

from composition import fit, state_digest


class CompositionTests(unittest.TestCase):
    def test_real_messages_gradients_ablation_budget_and_holdout_labels(self):
        rng = np.random.default_rng(33)
        x = rng.normal(size=(40, 12)).astype(np.float32)
        y = (x[:, 0] * x[:, 1] > 0).astype(int)
        split = ["train"] * 24 + ["select"] * 8 + ["test"] * 8
        arms = fit(x, y, split, steps=8)
        poisoned = y.copy()
        poisoned[24:] = 1 - poisoned[24:]
        other = fit(x, poisoned, split, steps=8)
        self.assertEqual(
            len({model.trainable_budget for model, _, _ in arms.values()}), 1
        )
        for name, (model, values, receipt) in arms.items():
            self.assertEqual(state_digest(model), state_digest(other[name][0]))
            np.testing.assert_array_equal(values, other[name][1])
            self.assertEqual(receipt["steps"], 0 if name == "frozen" else 8)
        joint = arms["joint"][0]
        self.assertIsNotNone(joint.semantic.weight.grad)
        self.assertGreater(float(joint.semantic.weight.grad.abs().sum()), 0)
        self.assertGreater(float(joint.gate.weight.grad.abs().sum()), 0)
        self.assertNotEqual(state_digest(joint), state_digest(arms["frozen"][0]))

    def test_bad_data_and_no_train_support_reject(self):
        with self.assertRaises(ValueError):
            fit(np.zeros((4, 3)), np.zeros(4), ["test"] * 4)
        with self.assertRaises(ValueError):
            fit(np.full((4, 3), np.nan), np.array([0, 1, 0, 1]), ["train"] * 4)


if __name__ == "__main__":
    torch.set_num_threads(2)
    unittest.main()
