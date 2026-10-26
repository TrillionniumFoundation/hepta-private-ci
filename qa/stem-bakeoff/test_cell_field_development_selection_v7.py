"""Development triage cannot discard failures or promote weak old retention."""

from itertools import product
import unittest

import numpy as np

from cell_field_development_selection_v7 import (BASELINES, CANDIDATE, GROUPS, POLICIES, SEEDS,
    select_configuration, summarize_configuration)


def complete_rows(old=-0.03, gain=0.01):
    rows = []
    for (version, task, head), seed, policy in product(GROUPS, SEEDS, POLICIES):
        rows.append({"version": version, "task": task, "head": head, "seed": seed, "policy": policy,
            "status": "completed", "completed_steps": 32, "error": None, "audit_passed": True,
            "cpu_ns": 50 if policy == CANDIDATE else 100,
            "selection_sources_sha256": version+task,
            "future_losses": np.full(512, 0.5-gain if policy == CANDIDATE else 0.5),
            "old_differences": np.full(512, old if policy == CANDIDATE else -0.01)})
    return rows


class DevelopmentSelectionTests(unittest.TestCase):
    def test_full_eight_groups_and_sixteen_paired_comparisons(self):
        summary = summarize_configuration(0, complete_rows())
        self.assertTrue(summary["eligible"])
        self.assertTrue(summary["plausible"])
        self.assertEqual(len(summary["groups"]), 8)
        self.assertEqual(sum(len(g["future"]) for g in summary["groups"]), 16)
        for group in summary["groups"]:
            self.assertAlmostEqual(group["old_mean_difference"], -0.03)
            self.assertEqual([r["baseline"] for r in group["future"]], list(BASELINES))
            self.assertEqual(group["candidate_h1_cpu_ratio"], 0.5)

    def test_plausible_subset_wins_over_better_future_but_weak_old(self):
        summaries = [summarize_configuration(i, complete_rows(old=-0.001, gain=0.03)) for i in range(12)]
        summaries[5] = summarize_configuration(5, complete_rows())
        chosen = select_configuration(summaries)
        self.assertEqual(chosen["selected_index"], 5)
        self.assertTrue(chosen["confirmation_plausibility_passed"])
        self.assertFalse(chosen["scientific_acceptance"])
        self.assertFalse(chosen["fresh_confirmation_executed"])

    def test_stopped_missing_duplicate_nonfinite_or_error_remain_ineligible(self):
        mutations = [lambda r: r[0].update(completed_steps=24), lambda r: r.pop(),
            lambda r: r.append(dict(r[0])), lambda r: r[0].update(future_losses=np.full(512, np.nan)),
            lambda r: r[0].update(error={"type": "actual_execution_error"}),
            lambda r: r[0].update(selection_sources_sha256="other-source-order")]
        for mutate in mutations:
            rows = complete_rows()
            mutate(rows)
            self.assertFalse(summarize_configuration(0, rows)["eligible"])

    def test_costs_use_same_group_all_three_seeds(self):
        rows = complete_rows()
        for row in rows:
            if row["policy"] == CANDIDATE:
                row["cpu_ns"] = 301
        summary = summarize_configuration(0, rows)
        self.assertFalse(summary["eligible"])
        self.assertEqual([g["candidate_h1_cpu_ratio"] for g in summary["groups"]], [3.01]*8)

    def test_no_plausible_config_is_diagnostic_and_no_missing_config_allowed(self):
        summaries = [summarize_configuration(i, complete_rows(old=-0.001)) for i in range(12)]
        chosen = select_configuration(summaries)
        self.assertEqual(chosen["selected_index"], 0)
        self.assertEqual(chosen["selected_scope"], "diagnostic_only")
        self.assertFalse(chosen["confirmation_plausibility_passed"])
        with self.assertRaisesRegex(ValueError, "twelve"):
            select_configuration(summaries[:-1])


if __name__ == "__main__":
    unittest.main()
