"""Paired four-stage dispositions must reject reader and MemoryCell confounds."""

import unittest

from factorial_evidence_gate import analyze
from test_factorial_evidence_gate import fixture


class FourStageDispositionTests(unittest.TestCase):
    def test_oracle_success_is_not_semantic_sufficiency(self):
        plan, rows = fixture()
        report = analyze(plan, rows)
        stage = report["four_stage_disposition"]
        self.assertEqual(stage["stage_1_reader"]["frozen_oracle_success_rate"], 1)
        self.assertEqual(
            stage["stage_1_reader"]["next_priority"],
            "investigate_retrieval_selection_distractors_and_packing",
        )
        self.assertFalse(
            stage["stage_1_reader"]["reader_capability_independently_established"]
        )
        self.assertFalse(stage["stage_4_lifetime"]["production_accepted"])
        self.assertEqual(
            report["paired_task_diagnostics"]["frozen_oracle_vs_hybrid"]["wins"], 4
        )

    def test_strong_rag_ceiling_must_reject_empty_parameter_gain(self):
        plan, rows = fixture()
        for row in rows:
            if row["condition"] == "hybrid":
                row["success"] = True
        report = analyze(plan, rows)
        organized = report["paired_task_diagnostics"]["organized_vs_hybrid"]
        self.assertEqual((organized["wins"], organized["losses"]), (0, 0))
        self.assertEqual(organized["net_task_success_delta"], 0)
        for candidate in ("learned_read", "knowledge"):
            self.assertTrue(
                report["four_stage_disposition"]["stage_3_parametric"]["candidates"][
                    candidate
                ]["rejected_on_observed_tasks"]
            )
        self.assertFalse(report["parametric_learning_qualified"])

    def test_larger_reference_is_reader_capacity_not_memory_learning(self):
        plan, rows = fixture()
        for row in rows:
            if row["reader"] == "frozen" and row["condition"] == "oracle":
                row["success"] = False
        report = analyze(plan, rows)
        capacity = report["paired_task_diagnostics"]["reference_capacity_same_oracle"]
        self.assertEqual(capacity["wins"], 4)
        self.assertEqual(capacity["evidence_bytes_identity_matched_cases"], 4)
        self.assertEqual(
            report["four_stage_disposition"]["stage_1_reader"]["next_priority"],
            "audit_sufficiency_prompt_representation_and_reader_errors",
        )
        self.assertFalse(
            report["four_stage_disposition"]["stage_3_parametric"][
                "independent_heldout_gain_established"
            ]
        )

    def test_paired_outcomes_preserve_task_and_source_family_denominators(self):
        plan, rows = fixture()
        for row in rows:
            if (
                row["id"] == "case-0"
                and row["arm"] == "event_graph"
                and row["condition"] == "hybrid"
            ):
                row["success"] = True
                row["diagnostic_count"] = 1
                row["recovery_success"] = True
        report = analyze(plan, rows)
        effect = report["paired_task_diagnostics"]["organized_vs_hybrid"]
        self.assertEqual(
            (effect["wins"], effect["losses"], effect["planned"]), (1, 0, 4)
        )
        self.assertEqual(effect["diagnostic_count_delta"], -1)
        self.assertEqual(effect["recovery_wins"], 1)
        self.assertEqual(effect["by_kind"]["new_fact"]["wins"], 1)
        self.assertEqual(effect["by_root"]["family-0"]["planned"], 2)
        self.assertFalse(effect["statistical_superiority_established"])

    def test_premise_ablation_does_not_certify_necessary_context(self):
        plan, rows = fixture()
        for row in rows:
            if row["arm"] == "hybrid_rag" and row["reader"] == "frozen":
                if row["condition"] == "ablated":
                    row["success"] = True
        result = analyze(plan, rows)
        stage = result["four_stage_disposition"]["stage_1_reader"]
        self.assertEqual(stage["oracle_success_with_premise_removed"], 4)
        self.assertEqual(stage["oracle_success_lost_after_ablation"], 0)
        self.assertEqual(
            stage["next_priority"],
            "audit_removed_premise_independence_and_shortcut_paths",
        )
        self.assertTrue(stage["ablation_is_not_independent_necessity_proof"])

    def test_missing_lifetime_cost_remains_unknown(self):
        plan, rows = fixture()
        for row in rows:
            row["cost"]["maintenance"] = None
            row["cost"]["revocation"] = None
        report = analyze(plan, rows)
        lifetime = report["four_stage_disposition"]["stage_4_lifetime"]
        self.assertEqual(lifetime["missing_cost_fields"], ["maintenance", "revocation"])
        self.assertIsNone(lifetime["measured_query_reuse_break_even"])
        self.assertFalse(
            lifetime["maintenance_revocation_recovery_observed_in_production"]
        )


if __name__ == "__main__":
    unittest.main()
