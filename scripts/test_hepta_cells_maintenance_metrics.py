"""Cost windows retain failure, scope and unavailable-meter information."""

import unittest
from unittest.mock import patch

from hepta_cells.maintenance_metrics import Measurement, summarize_decisions, summarize_tasks


class MetricsTests(unittest.TestCase):
    def test_nested_windows_are_separate_and_unknown_resources_stay_unknown(self):
        with patch("hepta_cells.maintenance_metrics._usage", return_value=None):
            with Measurement("campaign", "outer") as outer:
                with Measurement("training", "fit", parent_scope="outer") as inner:
                    sum(range(100))
        self.assertGreaterEqual(outer.result["wall_ns"], inner.result["wall_ns"])
        for metric in (outer, inner):
            self.assertIsNone(metric.result["resource_after"])
            self.assertIsNone(metric.result["reaped_children_cpu_seconds"])
            self.assertIsNone(metric.result["energy_joules"])
            self.assertFalse(metric.result["additive"])
        self.assertEqual(inner.result["parent_scope"], "outer")

    def test_failure_is_measured_and_reraised_without_erasing_cause(self):
        meter = Measurement("verification", "broken-check")
        with self.assertRaisesRegex(RuntimeError, "verification failed"):
            with meter:
                raise RuntimeError("verification failed")
        self.assertEqual((meter.result["status"], meter.result["error_type"]), ("raised", "RuntimeError"))
        self.assertGreaterEqual(meter.result["wall_ns"], 0)
        with self.assertRaisesRegex(ValueError, "reused"):
            with meter:
                pass

    def test_percentiles_report_missing_coverage_and_reject_invalid_duration(self):
        result = summarize_tasks([{"wall_ns": 1_000_000}, {}, {"wall_ns": 3_000_000}], scope="whole tasks")
        self.assertEqual((result["count"], result["observed_count"], result["missing_count"]), (3, 2, 1))
        self.assertEqual(result["observed_p50_ms"], 2.0)
        self.assertAlmostEqual(result["observed_p95_ms"], 2.9)
        self.assertFalse(result["coverage_complete"])
        for invalid in (True, -1, 1.0, "3"):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                summarize_tasks([{"wall_ns": invalid}], scope="whole tasks")
        empty = summarize_tasks([], scope="unobserved")
        self.assertIsNone(empty["observed_p99_ms"])
        self.assertFalse(empty["coverage_complete"])

    def test_no_update_rate_uses_only_complete_decisions_and_preserves_reasons(self):
        result = summarize_decisions([
            {"decision": "Adopt", "reason": "held-out gain"},
            {"decision": "NoUpdate", "reason": "cost"},
            {"decision": "NoUpdate", "reason": "cost"},
        ])
        self.assertEqual(result, {"completed_decisions": 3, "adopt": 1, "no_update": 2, "no_update_fraction": 2 / 3, "no_update_reasons": {"cost": 2}})
        with self.assertRaises(ValueError):
            summarize_decisions([{"decision": "pending", "reason": "unknown"}])
        self.assertIsNone(summarize_decisions([])["no_update_fraction"])

    def test_campaign_summary_keeps_failed_task_and_nested_scope(self):
        from hepta_cells.maintenance_cycle import cost_summary
        from hepta_cells.maintenance_serving import measure_window
        windows = []
        with self.assertRaisesRegex(RuntimeError, "semantic child failed"):
            with measure_window(windows, "validation", "all B arms"):
                with measure_window(windows, "task", "serve and semantic check", cell="memory", phase="B", arm="candidate", task_id="task-1", diagnostic_scope="shared original excluded"):
                    raise RuntimeError("semantic child failed")
        summary = cost_summary(windows, {})
        self.assertEqual(len(summary["windows"]), 2)
        self.assertEqual(summary["task_latency"]["memory/B/candidate"]["observed_count"], 1)
        self.assertEqual(windows[1]["measurement"]["status"], "raised")
        self.assertEqual(windows[1]["diagnostic_scope"], "shared original excluded")
        self.assertFalse(summary["full_system_cost_known"])
        self.assertIsNone(summary["decisions"]["no_update_fraction"])


if __name__ == "__main__":
    unittest.main()
