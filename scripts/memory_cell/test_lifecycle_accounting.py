"""Counterexamples for honest cost and task accounting; no pretrained model."""

from dataclasses import replace
import math
import unittest

from lifecycle_accounting import Envelope, paired_task_contrasts, reuse_projection, summarize_envelopes


def measured(name, phase, seconds, parent=None):
    return Envelope(name, phase, seconds, "a" * 64, "fixture-process", parent)


class LifecycleAccountingTests(unittest.TestCase):
    def test_inclusive_training_and_inference_are_counted_once(self):
        rows = [measured("extract", "extract", 1), measured("index", "index", 2),
                measured("write", "write", 10), measured("training", "train", 8, "write"),
                measured("read", "read", 6), measured("model", "read", 5, "read"),
                measured("maintain", "maintain", 0), measured("recover", "recover", 3)]
        value = summarize_envelopes(rows)
        self.assertEqual(value["recorded_root_seconds"], 22)
        self.assertEqual(value["complete_recorded_seconds"], 22)
        self.assertIsNone(value["production_lifecycle_cost"])
        self.assertNotIn("training", value["inclusive_root_ids"])

    def test_unknown_root_is_not_replaced_by_child_or_zero(self):
        result = summarize_envelopes([measured("write", "write", None),
                                     measured("train", "train", 8, "write")])
        self.assertIsNone(result["complete_recorded_seconds"])
        self.assertEqual(result["recorded_root_seconds"], 0)
        self.assertEqual(result["unknown_root_ids"], ["write"])
        self.assertIn("maintain", result["missing_phases"])

    def test_invalid_graph_and_numeric_measurements_reject(self):
        base = measured("write", "write", 5)
        cases = [[base, base], [replace(base, parent="absent")],
                 [replace(base, parent="write")],
                 [replace(base, parent="child"), measured("child", "train", 2, "write")],
                 [base, measured("child", "train", 6, "write")],
                 [base, replace(measured("child", "train", 2, "write"), clock_domain="other")]]
        cases.extend([[replace(base, seconds=x)] for x in (True, -1, math.nan, math.inf)])
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                summarize_envelopes(case)

    def test_unknown_lifecycle_terms_cannot_produce_a_break_even_claim(self):
        result = reuse_projection(fixed_seconds=20, read_seconds_per_query=2,
                                  maintenance_seconds_per_query=None,
                                  recovery_seconds_per_query=None, queries=[1, 10])
        self.assertEqual([r["measured_terms_projection_seconds"] for r in result["horizons"]], [22, 40])
        self.assertTrue(all(r["complete_projection_seconds"] is None for r in result["horizons"]))
        self.assertFalse(result["economic_or_quality_advantage_established"])

    def test_complete_curve_keeps_all_cost_terms_and_validates_horizon(self):
        args = dict(fixed_seconds=20, read_seconds_per_query=2,
                    maintenance_seconds_per_query=1, recovery_seconds_per_query=0.5)
        value = reuse_projection(**args, queries=[10])["horizons"][0]
        self.assertEqual(value["complete_projection_seconds"], 55)
        self.assertEqual(value["complete_amortized_seconds"], 5.5)
        for queries in ([], [True], [0], [1, 1]):
            with self.assertRaises(ValueError):
                reuse_projection(**args, queries=queries)

    def test_more_selected_sources_without_a_task_win_is_not_a_gain(self):
        rows = [dict(question_id="q", arm=a, kind="procedure", candidate_digest="pool",
                     selected=[a], status="succeeded", strict_task_success=True)
                for a in ("hybrid", "organized", "learned")]
        value = paired_task_contrasts(rows, ["q"], ["hybrid", "organized", "learned"], "learned")
        self.assertFalse(value["organized"]["observed_positive_difference"])
        self.assertEqual(value["organized"]["changed_selection_without_task_win"], 1)
        rows[0]["strict_task_success"] = False
        self.assertTrue(paired_task_contrasts(rows, ["q"], ["hybrid", "organized", "learned"], "learned")["hybrid"]["observed_positive_difference"])

    def test_failed_attempts_preserve_full_denominator_and_ambiguity(self):
        rows = [dict(question_id="q", arm=a, kind="new_fact", candidate_digest="p",
                     selected=[], status="succeeded", strict_task_success=True)
                for a in ("base", "learned")]
        rows[1].update(status="failed", strict_task_success=None)
        value = paired_task_contrasts(rows, ["q"], ["base", "learned"], "learned")["base"]
        self.assertEqual(value["all_planned_effect_bounds"], [-1, 1])
        rows[1]["strict_task_success"] = True
        with self.assertRaises(ValueError):
            paired_task_contrasts(rows, ["q"], ["base", "learned"], "learned")

    def test_pool_drift_and_duplicate_census_reject(self):
        rows = [dict(question_id="q", arm=a, kind="new_fact", candidate_digest=a,
                     selected=[], status="succeeded", strict_task_success=True)
                for a in ("base", "learned")]
        with self.assertRaises(ValueError):
            paired_task_contrasts(rows, ["q"], ["base", "learned"], "learned")
        with self.assertRaises(ValueError):
            paired_task_contrasts(rows + rows, ["q"], ["base", "learned"], "learned")


if __name__ == "__main__":
    unittest.main()
