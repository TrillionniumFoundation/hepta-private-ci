"""Synthetic composition regressions, never physical or independent evidence."""

import copy
import unittest

from cell_split import GateError, compare as compare_cells
from compare import ComparisonError, compare
from test_cell_split import fixture as cell_fixture
from test_compare import fixture


class IntegratedGateTests(unittest.TestCase):
    def test_equal_aggregate_success_cannot_hide_paired_4096_regression(self):
        base, rows = fixture()
        task = copy.deepcopy(base["tasks"][0])
        task["task_id"] = "second-task"
        base["tasks"].append(task)
        extra = copy.deepcopy(rows)
        for index, row in enumerate(extra):
            row["task_id"] = task["task_id"]
            row["observation_digest"] = f"{1000 + index:064x}"
        rows += extra
        for row in rows:
            if row["scale"] == 4096:
                row["task_success"] = (row["task_id"] == "second-task") == (
                    row["mode"] == "C"
                )
                if row["mode"] == "C":
                    row["cpu_ms"] += 25
                    row["peak_gpu_memory_bytes"] = 1024
                    row["active_concurrency"] = 2
        result = compare(base, rows)
        self.assertEqual(
            result["scale_deltas"]["4096"]["C_vs_A"]["success_rate_delta"], 0
        )
        paired = result["paired_effects_by_scale"]["4096"]["C_vs_A"]
        self.assertEqual(
            paired["quality"]["task_success"],
            {
                "native_only_passes": 1,
                "reference_only_passes": 1,
                "paired_delta_percentage_points": 0.0,
            },
        )
        self.assertTrue(paired["any_paired_quality_regression"])
        self.assertEqual(paired["mean_resource_delta_C_minus_reference"]["cpu_ms"], 25)
        self.assertEqual(
            paired["mean_resource_delta_C_minus_reference"]["peak_gpu_memory_bytes"],
            1024,
        )
        self.assertEqual(
            paired["mean_resource_delta_C_minus_reference"]["active_concurrency"], 1
        )
        self.assertFalse(
            result["paired_effects_by_scale"]["64"]["C_vs_A"][
                "any_paired_quality_regression"
            ]
        )
        self.assertFalse(result["independent_acceptance"])
        self.assertFalse(paired["statistical_significance_proven"])

    def test_pairing_does_not_bypass_latest_executable_or_cpu_guards(self):
        for field, value, reason in (
            ("mode_build_digest", "f" * 64, "built artifact"),
            ("cpu_ms", 90000, "CPU budget overrun"),
            ("source_trees", {}, "source tree drift"),
        ):
            with self.subTest(field=field):
                base, rows = fixture()
                rows[-1][field] = value
                with self.assertRaisesRegex(ComparisonError, reason):
                    compare(base, rows)

    def test_family_and_cost_guards_are_both_preserved(self):
        plan, rows = cell_fixture()
        # The cost/provenance parent accepted this correlated family alias.
        plan["tasks"][3]["family"] = plan["tasks"][2]["family"]
        with self.assertRaisesRegex(GateError, "family crosses independent groups"):
            compare_cells(plan, rows)
        plan, rows = cell_fixture()
        for row in rows:
            if row["arm"] == "split" and row["scale"] == 4096:
                row["cpu_ms"] *= 2
        result = compare_cells(plan, rows)
        self.assertFalse(result["all_scales_meet_structural_metrics"])
        self.assertFalse(result["scales"]["4096"]["resource_cost_guard"]["cpu"])
        self.assertFalse(result["independent_acceptance"])


if __name__ == "__main__":
    unittest.main()
