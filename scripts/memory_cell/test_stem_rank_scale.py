"""Synthetic residual geometry: not evidence of pretrained task gains."""

import math
import unittest

from stem_rank_scale import minimum_residual_flip_scale as limit
from stem_cell_geometry import inspect_selection, summarize_geometry


class ResidualRankScaleTests(unittest.TestCase):
    def test_small_correct_direction_requires_sixfold_amplification(self):
        self.assertEqual(limit([8, 2], [7.5, 2.5], ("a", "b")), 6)
        row = inspect_selection([8, 2], [7.5, 2.5], ("a", "b"), 0)
        self.assertEqual(row["joint_flip_scale_infimum"], 6)
        self.assertIsNone(row["encoder_only_flip_scale_infimum"])
        self.assertFalse(row["changed_selected_candidate"])

    def test_large_uniform_or_wrong_direction_never_overcomes_margin(self):
        for altered in ([1008, 1002], [8.7, 2.3], [8, 2]):
            self.assertIsNone(limit([8, 2], altered, ("a", "b")))

    def test_observed_flip_has_infimum_below_one(self):
        row = inspect_selection([8, 2], [4, 9], ("a", "b"), 1)
        self.assertTrue(row["changed_selected_candidate"])
        self.assertTrue(math.isclose(row["joint_flip_scale_infimum"], 6 / 11))
        self.assertTrue(row["residual_scaling_is_not_a_validated_policy"])

    def test_lexical_tie_is_an_infimum_not_a_flip_at_zero(self):
        self.assertEqual(limit([0, 0], [2, 1], ("B", "A")), 0)
        self.assertIsNone(limit([0, 0], [1, 2], ("B", "A")))

    def test_encoder_only_flip_can_be_cancelled_by_head(self):
        row = inspect_selection(
            [3, 9],
            [8, 2],
            ("a", "b"),
            0,
            original_frozen_scores=[8, 2],
            encoder_adapted=True,
        )
        self.assertTrue(row["encoder_only_changed_selected_candidate"])
        self.assertTrue(row["head_changed_selected_candidate"])
        self.assertFalse(row["changed_selected_candidate"])
        self.assertIsNotNone(row["encoder_only_flip_scale_infimum"])
        self.assertIsNotNone(row["head_conditional_flip_scale_infimum"])
        self.assertIsNone(row["joint_flip_scale_infimum"])

    def test_incomplete_read_does_not_delete_pre_read_geometry(self):
        can_flip = inspect_selection([8, 2], [7.5, 2.5], ("a", "b"), 0)
        cannot = inspect_selection([8, 2], [8.7, 2.3], ("a", "b"), 0)
        rows = [
            dict(
                stage=48,
                phase="test",
                arm="gated",
                status="succeeded",
                selection_geometry=can_flip,
            ),
            dict(
                stage=48,
                phase="test",
                arm="gated",
                status="failed",
                selection_geometry=cannot,
            ),
            dict(stage=48, phase="test", arm="gated", status="failed"),
        ]
        summary = summarize_geometry(rows)["48/test/gated"]
        self.assertEqual(summary["observed_pre_reader_decisions"], 2)
        self.assertEqual(summary["joint_direction_can_flip_count"], 1)
        self.assertEqual(summary["joint_direction_cannot_flip_count"], 1)
        self.assertEqual(summary["joint_requires_scale_above_one_count"], 1)
        self.assertFalse(summary["verified_new_correct_evidence_gain"])

    def test_missing_pool_has_no_artificial_flip(self):
        self.assertIsNone(limit([], [], []))
        self.assertIsNone(limit([1], [8], ("only",)))

    def test_nan_overflow_bool_duplicate_and_misalignment_rejected(self):
        for frozen, after, ids in (
            ([1, 2], [2, 1], ("x", "x")),
            ([1, float("inf")], [2, 1], ("x", "y")),
            ([1, 2], [2, float("nan")], ("x", "y")),
            ([1, 2], [1], ("x", "y")),
            ([True, 2], [1, 2], ("x", "y")),
            ([1e308, -1e308], [-1e308, 1e308], ("x", "y")),
        ):
            with self.subTest(frozen=frozen), self.assertRaises(ValueError):
                limit(frozen, after, ids)


if __name__ == "__main__":
    unittest.main()
