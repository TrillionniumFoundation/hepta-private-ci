"""Source-only arithmetic negatives and original material optional suite entrypoint."""
import unittest

import numpy as np

from v18_paired_damage import Invalid, stats_from_logits


class Tests(unittest.TestCase):
    def test_rescue_and_harm(self):
        base = [[3, 0, 0, 0], [3, 0, 0, 0], [0, 3, 0, 0]]
        cand = [[0, 3, 0, 0], [3, 0, 0, 0], [0, 3, 0, 0]]
        out = stats_from_logits(base, cand, [1, 0, 0])
        self.assertEqual(out['rescued_baseline_errors'], 1)
        self.assertEqual(out['damaged_baseline_correct'], 0)
        self.assertEqual(out['net_correct_change'], 1)
        self.assertEqual(out['same_correctness'], 2)
    def test_repeat_is_not_gain(self):
        x = [[0, 0, 0, 0]] * 3
        out = stats_from_logits(x, x, [0, 1, 2])
        self.assertEqual(out['net_correct_change'], 0)
        self.assertFalse(out['historical_gate_would_pass'])
    def test_mismatch(self):
        self.assertRaises(Invalid, stats_from_logits, [[1, 2, 3, 4]], [[1, 2, 3]], [0])
    def test_nan(self):
        self.assertRaises(Invalid, stats_from_logits, [[float('nan'), 0, 0, 0]], [[1, 0, 0, 0]], [0])
    def test_infinity(self):
        self.assertRaises(Invalid, stats_from_logits, [[float('inf'), 0, 0, 0]], [[1, 0, 0, 0]], [0])
    def test_noninteger_label(self):
        self.assertRaises(Invalid, stats_from_logits, [[1, 0, 0, 0]], [[1, 0, 0, 0]], [1.5])
    def test_invalid_label(self):
        self.assertRaises(Invalid, stats_from_logits, [[1, 0, 0, 0]], [[1, 0, 0, 0]], [4])
    def test_empty(self):
        self.assertRaises(Invalid, stats_from_logits, [], [], [])
    def test_double_baseline_is_zero(self):
        a = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], dtype=float)
        out = stats_from_logits(a, a, [0, 1])
        self.assertEqual(out['mean_brier_delta_candidate_minus_baseline'], 0)
        self.assertEqual(out['rescued_baseline_errors'], 0)
    def test_column_dim(self):
        self.assertRaises(Invalid, stats_from_logits, [[0] * 5], [[0] * 5], [1])

if __name__ == '__main__':
    unittest.main()
