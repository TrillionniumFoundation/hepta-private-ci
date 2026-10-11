"""Synthetic rank geometry tests, not true native QA performance evidence."""

import unittest

from stem_cell_geometry import inspect_selection, summarize_geometry


class RankGeometryTests(unittest.TestCase):
    def test_single_window_cannot_change_forced_top1(self):
        result = inspect_selection([24.0], [25.0], ("source",), 0)
        self.assertTrue(result["forced_top1"])
        self.assertFalse(result["has_ranking_competition"])
        self.assertFalse(result["changed_selected_candidate"])
        self.assertIsNone(result["frozen_top1_gap"])
        self.assertEqual(result["max_abs_score_delta"], 1.0)

    def test_no_windows_is_recorded_without_fabricated_null(self):
        result = inspect_selection([], [], (), None)
        self.assertTrue(result["empty_pool"])
        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(result["max_abs_score_delta"], 0)
        self.assertFalse(result["no_answer_policy_calibrated"])

    def test_small_residual_cannot_defeat_large_native_margin(self):
        item = inspect_selection([8.0, 2.0], [7.5, 2.5], ("A", "B"), 0)
        self.assertEqual(item["frozen_top1_gap"], 6.0)
        self.assertEqual(item["learned_top1_gap"], 5.0)
        self.assertTrue(item["gap_exceeds_twice_max_residual"])
        self.assertFalse(item["changed_selected_candidate"])

    def test_real_ranking_flip_is_explicit(self):
        item = inspect_selection([8.0, 2.0], [4.0, 9.0], ("A", "B"), 1)
        self.assertFalse(item["gap_exceeds_twice_max_residual"])
        self.assertEqual(item["baseline_top_id"], "A")
        self.assertEqual(item["learned_top_id"], "B")
        self.assertTrue(item["changed_selected_candidate"])

    def test_equal_scores_use_native_lexical_tie_break(self):
        item = inspect_selection([0.0, 0.0], [1.0, 1.0], ("B", "A"), 1)
        self.assertEqual(item["baseline_top_id"], "A")
        self.assertEqual(item["learned_top_id"], "A")
        self.assertEqual(item["selected_index"], 1)

    def test_wrong_predicted_selection_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "policy selection differs"):
            inspect_selection([2.0, 1.0], [2.0, 1.0], ("A", "B"), 1)

    def test_malformed_nonfinite_duplicate_inputs_fail_closed(self):
        for baseline, head, identifiers, selected in (
            ([1], [1], ("A", "A"), 0),
            ([1, float("nan")], [1, 2], ("A", "B"), 1),
            ([1, 2], [1, float("inf")], ("A", "B"), 0),
            ([1, 2], [1], ("A", "B"), 0),
            ([1], [1], ("",), 0),
        ):
            with self.subTest(scores=baseline), self.assertRaises(ValueError):
                inspect_selection(baseline, head, identifiers, selected)

    def test_generation_failure_still_counts_pre_reader_selection(self):
        stable = inspect_selection([5.0, 1.0], [6.0, 1.5], ("A", "B"), 0)
        change = inspect_selection([3.0, 2.0], [1.0, 4.0], ("A", "B"), 1)
        rows = [
            dict(stage=16, phase="test", arm="gated", status="succeeded",
                 selection_geometry=stable),
            dict(stage=16, phase="test", arm="gated", status="failed",
                 selection_geometry=change),
            dict(stage=16, phase="test", arm="gated", status="failed"),
        ]
        out = summarize_geometry(rows)["16/test/gated"]
        self.assertEqual(out["observed_pre_reader_decisions"], 2)
        self.assertEqual(out["changed_top1_count"], 1)
        self.assertEqual(out["competing_pools"], 2)
        self.assertFalse(out["verified_new_correct_evidence_gain"])
        self.assertIsNone(out["semantic_citation_precision"])


if __name__ == "__main__":
    unittest.main()
