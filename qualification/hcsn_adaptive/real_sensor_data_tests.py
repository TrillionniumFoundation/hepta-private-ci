"""Behavior checks for chronology, sensor leakage, and exact elapsed time."""

import unittest

import numpy as np

from .real_sensor_data import FEATURES, make_splits


class SensorWindowsTests(unittest.TestCase):
    def test_future_targets_and_disjoint_chronology(self):
        n = 600
        x = np.arange(n*len(FEATURES), dtype=np.float64).reshape(n, -1)
        stamps = np.cumsum(np.resize([29, 30, 31], n)).astype(np.int64)
        labels = np.arange(n) % 4
        splits, report = make_splits(x, labels, stamps, length=8)
        all_ids = []
        previous_end = -1
        for name in ("train", "dev", "test"):
            s = splits[name]
            self.assertTrue(np.all(s["target_times"] > s["input_times"][:, -1]))
            expected = np.diff(np.c_[s["input_times"], s["target_times"]], axis=1)
            np.testing.assert_array_equal(s["dt"], expected)
            self.assertGreater(int(s["input_times"].min()), previous_end)
            previous_end = int(s["target_times"].max())
            all_ids.extend(s["ids"].tolist())
        self.assertEqual(len(all_ids), len(set(all_ids)))
        self.assertEqual(report["stride"], 9)

    def test_heldout_values_cannot_change_training_normalization(self):
        x = np.zeros((600, len(FEATURES)))
        stamps = np.arange(600, dtype=np.int64)*30
        labels = np.zeros(600, dtype=np.int64)
        a, report_a = make_splits(x, labels, stamps, length=8)
        x[360:] = 1e6
        labels[360:] = 3
        b, report_b = make_splits(x, labels, stamps, length=8)
        self.assertEqual(report_a["normalization_train_only"], report_b["normalization_train_only"])
        for key in a["train"]:
            np.testing.assert_array_equal(a["train"][key], b["train"][key])

    def test_real_gaps_are_not_interpolated(self):
        x = np.zeros((600, len(FEATURES)))
        stamps = np.arange(600, dtype=np.int64)*30
        stamps[150:] += 86400
        splits, _ = make_splits(x, np.zeros(600, dtype=np.int64), stamps, length=8)
        self.assertTrue(all(np.max(s["dt"]) <= 300 for s in splits.values()))


if __name__ == "__main__":
    unittest.main()
