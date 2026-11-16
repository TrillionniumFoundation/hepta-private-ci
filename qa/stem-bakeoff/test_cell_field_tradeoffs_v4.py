"""Independent cost arithmetic, direction/amplitude separation and failure census."""

import copy
import math
import unittest

from cell_field_fixed_actions import fixed_library
from cell_field_tradeoffs_v4 import summarize_fixed_actions


class TradeoffTests(unittest.TestCase):
    def rows(self):
        rows = []
        for index, (name, u) in enumerate(fixed_library(36)):
            physical = [0.02 * v for v in u]
            effort = 0.1 / (2 * 0.02) * math.fsum(v * v for v in physical)
            risk = math.fsum((j + 1) * v for j, v in enumerate(u)) * 1e-4
            forgetting = max(0, risk) ** 2 / 2
            rows.append({"action_id": name, "u": list(u), "status": "completed",
                         "scores": {"direct_current": risk, "forgetting": forgetting,
                                    "effort": effort, "direct_soft_total": risk + forgetting + effort},
                         "cpu_ns": index + 1, "wall_ns": 2 * (index + 1)})
        return rows

    def test_complete_directions_amplitudes_and_actual_resource_sums(self):
        result = summarize_fixed_actions(self.rows(), parameters=36)
        self.assertEqual((result["registered"], result["completed"]), (49, 49))
        self.assertEqual(len(result["same_norm_directions"]), 3)
        self.assertEqual(len(result["fixed_direction_amplitudes"]), 16)
        for group in result["same_norm_directions"]:
            self.assertEqual(len(group["entries"]), 16)
            self.assertTrue(group["complete"])
            self.assertLess(max(row["effort"] for row in group["entries"])
                            - min(row["effort"] for row in group["entries"]), 1e-16)
        for group in result["fixed_direction_amplitudes"]:
            self.assertEqual(len(group["entries"]), 4)
            self.assertEqual(group["entries"][0]["action_id"], "zero")
            penalties = [row["effort"] for row in group["entries"]]
            self.assertAlmostEqual(penalties[2] / penalties[1], 16.0)
            self.assertAlmostEqual(penalties[3] / penalties[2], 4.0)
        self.assertEqual(result["resources"]["cpu_ns"], {"observed_total": 1225, "measured_branches": 49})
        self.assertEqual(result["resources"]["wall_ns"]["observed_total"], 2450)
        self.assertLess(result["maximum_identity_residual"], 1e-16)

    def test_failed_actions_are_preserved_without_success_only_range_or_unknown_zero_cost(self):
        rows = self.rows()
        rows[1].update(status="execution_failed", scores=None, cpu_ns=None, wall_ns=None, error={"type": "timeout"})
        result = summarize_fixed_actions(rows, parameters=36)
        self.assertEqual(result["completed"], 48)
        self.assertFalse(result["same_norm_directions"][0]["complete"])
        self.assertIsNone(result["same_norm_directions"][0]["actual_current_risk_range"])
        self.assertEqual(result["resources"]["cpu_ns"]["measured_branches"], 48)
        failed = result["all_actions"][1]
        self.assertIsNone(failed["direct_soft_total"])
        self.assertIsNone(failed["difference_from_zero"])
        self.assertEqual(failed["error"], {"type": "timeout"})

    def test_missing_actions_changed_amplitudes_cost_alias_and_fake_timing_reject(self):
        rows = self.rows()
        with self.assertRaises(ValueError):
            summarize_fixed_actions(rows[:-1], parameters=36)
        for mutation in ("action", "effort", "sum", "time"):
            bad = copy.deepcopy(rows)
            if mutation == "action":
                bad[1]["u"][0] += 1e-5
            elif mutation == "effort":
                bad[1]["scores"]["effort"] += 0.01
            elif mutation == "sum":
                bad[1]["scores"]["direct_soft_total"] += 0.01
            else:
                bad[1]["cpu_ns"] = None
            with self.assertRaises(ValueError, msg=mutation):
                summarize_fixed_actions(bad, parameters=36)


if __name__ == "__main__":
    unittest.main()
