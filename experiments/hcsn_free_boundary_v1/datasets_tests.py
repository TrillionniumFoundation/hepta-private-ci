"""Causal task construction and source-isolation checks."""

import unittest

import numpy as np

from .datasets import synthetic


class DatasetTests(unittest.TestCase):
    def test_selected_answers_follow_marked_past_tokens(self):
        x, _, y, _ = synthetic("selective_copy", 40, "train")
        for inputs, targets in zip(x, y, strict=True):
            marked = np.flatnonzero(inputs[:, 8])
            np.testing.assert_array_equal(targets[-4:], inputs[marked, :8].argmax(-1))
            self.assertEqual(float(inputs[-4:, :9].sum()), 0)

    def test_mqar_answers_require_key_value_binding(self):
        x, _, y, _ = synthetic("mqar", 40, "test")
        for inputs, targets in zip(x, y, strict=True):
            stored = np.flatnonzero(inputs[:, 16])
            lookup = {int(inputs[t, :8].argmax()): int(inputs[t, 8:16].argmax())
                      for t in stored}
            expected = [lookup[int(q[:8].argmax())] for q in inputs[-4:]]
            np.testing.assert_array_equal(targets[-4:], expected)
            self.assertEqual(float(inputs[-4:, 8:16].sum()), 0)

    def test_irregular_target_matches_independent_weighted_sum(self):
        x, dt, y, _ = synthetic("irregular", 60, "ood", length=64)
        active_dt = dt[:, :-1].astype(np.float64)
        after = active_dt[:, ::-1].cumsum(1)[:, ::-1] - active_dt
        weights = -np.expm1(-0.2 * active_dt) * np.exp(-0.2 * after)
        expected = ((weights * x[:, :-1, 0]).sum(1) > 0).astype(np.int64)
        np.testing.assert_array_equal(y[:, -1], expected)

    def test_splits_reproducible_and_distinct(self):
        for task in ("selective_copy", "mqar", "irregular"):
            first = synthetic(task, 20, "train")
            second = synthetic(task, 20, "train")
            heldout = synthetic(task, 20, "test")
            for a, b in zip(first[:3], second[:3], strict=True):
                np.testing.assert_array_equal(a, b)
            self.assertFalse(np.array_equal(first[0], heldout[0]))
            self.assertFalse(set(first[3]["episode_ids"]) & set(heldout[3]["episode_ids"]))


if __name__ == "__main__":
    unittest.main()
