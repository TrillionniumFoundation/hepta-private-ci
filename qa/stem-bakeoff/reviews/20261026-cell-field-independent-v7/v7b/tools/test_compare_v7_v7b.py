"""Unequal stopped prefixes and all-source endpoint comparison semantics."""

import unittest

import numpy as np

from compare_v7_v7b import array_changes


class CompleteComparisonTests(unittest.TestCase):
    def test_unequal_prefix_is_retained_with_actual_distinct_endpoints(self):
        old = {"actions": np.ones((8, 36)), "terminal_vector": np.arange(108.),
            "future_losses": np.linspace(.1, 2., 512), "old_differences": np.linspace(-.1, .2, 512)}
        new = {key: value.copy() for key, value in old.items()}
        new.update(actions=np.ones((32, 36)), terminal_vector=old["terminal_vector"]+.125,
            future_losses=old["future_losses"]-.0625, old_differences=old["old_differences"]-.03125)
        row = array_changes(old, new)
        self.assertEqual((row["original_action_steps"], row["corrected_action_steps"], row["common_action_steps"]), (8, 32, 8))
        self.assertTrue(row["common_action_prefix_identical"])
        self.assertFalse(row["actions_identical"])
        self.assertEqual(row["maximum_terminal_state_absolute_difference"], .125)
        self.assertAlmostEqual(row["future_mean_nll_change_corrected_minus_original"], -.0625)
        self.assertAlmostEqual(row["old_mean_difference_change_corrected_minus_original"], -.03125)

    def test_one_source_change_is_not_hidden_by_equal_average(self):
        old = {"actions": np.zeros((0, 36)), "terminal_vector": np.zeros(108),
            "future_losses": np.ones(512), "old_differences": np.zeros(512)}
        new = {key: value.copy() for key, value in old.items()}
        new["future_losses"][:2] = [.5, 1.5]
        row = array_changes(old, new)
        self.assertEqual(row["future_mean_nll_change_corrected_minus_original"], 0.)
        self.assertFalse(row["future_source_losses_identical"])
        self.assertEqual(row["maximum_future_source_loss_absolute_change"], .5)
        self.assertEqual(row["common_action_steps"], 0)

    def test_signed_zero_is_numerically_equal_but_not_byte_identical(self):
        old = {"actions": np.zeros((1, 36)), "terminal_vector": np.zeros(108),
            "future_losses": np.ones(512), "old_differences": np.zeros(512)}
        new = {key: value.copy() for key, value in old.items()}
        new["actions"][0, 0] = -0.
        row = array_changes(old, new)
        self.assertTrue(row["actions_identical"])
        self.assertFalse(row["action_bytes_identical"])
        self.assertFalse(row["common_action_prefix_bytes_identical"])


if __name__ == "__main__":
    unittest.main()
