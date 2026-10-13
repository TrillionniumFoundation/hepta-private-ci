"""Tests use synthetic task outcomes, not new pretrained model answers."""

import copy
import unittest

from source_write_disposition import research_dispositions
from source_write_effects import effects
from test_source_write_effects import fixture


class WriteDispositionTests(unittest.TestCase):
    def test_all_controls_and_saturation_reject_unearned_learning_gain(self):
        raw, scored, cases = fixture()
        result = effects(raw, scored, cases)
        decisions = result["candidate_research_dispositions"]
        self.assertEqual(decisions["schema"], "hepta.source-write.research-dispositions.v1")
        policy = decisions["candidates"]["learned_policy"]
        self.assertEqual(policy["disposition"], "reject_no_increment_over_controls")
        self.assertEqual(policy["comparisons"]["hybrid"]["wins"], 2)
        self.assertEqual(policy["comparisons"]["organized"]["wins"], 0)
        self.assertTrue(policy["strongest_control_saturated"])
        knowledge = decisions["candidates"]["knowledge"]
        self.assertEqual(knowledge["disposition"], "reject_no_increment_over_controls")
        self.assertEqual(knowledge["comparisons"]["organized"]["wins"], 0)
        self.assertEqual(
            decisions["candidates"]["parameter_only"]["disposition"],
            "compression_boundary_only",
        )
        self.assertFalse(decisions["production_accepted"])

    def test_source_free_labels_cannot_become_independent_semantic_precision(self):
        raw, scored, cases = fixture()
        for group in (raw, scored):
            for item in group:
                if item["arm"] == "parameter_only":
                    item["answer"] = "value [E1]"
        result = effects(raw, scored, cases)["candidate_research_dispositions"]
        candidate = result["candidates"]["parameter_only"]
        self.assertEqual(candidate["citations_without_any_evidence"], 2)
        self.assertEqual(candidate["unsupported_citation_occurrences"], 2)
        self.assertTrue(candidate["unsupported_citations_require_separate_semantic_review"])
        self.assertIsNone(result["formal_semantic_citation_precision"])
        self.assertFalse(candidate["use_as_selected_production_memory"])

    def test_failures_cannot_hide_in_pairwise_optimization(self):
        raw, scored, cases = fixture()
        pos = next(i for i, r in enumerate(raw) if r["arm"] == "knowledge")
        raw[pos] = {
            k: v for k, v in raw[pos].items() if k not in ("answer", "receipt")
        }
        raw[pos].update(status="failed", error_type="TimeoutError")
        scored[pos] = copy.deepcopy(raw[pos])
        finding = effects(raw, scored, cases)["candidate_research_dispositions"]
        decision = finding["candidates"]["knowledge"]
        self.assertEqual(decision["disposition"], "inconclusive_incomplete_execution")
        self.assertEqual(decision["comparisons"]["organized"]["missing_pairs"], 1)
        self.assertFalse(decision["use_as_selected_production_memory"])

    def test_detects_a_non_saturated_effect_but_never_approves_it(self):
        raw, scored, cases = fixture()
        for item in scored:
            if item["arm"] == "organized":
                item["strict_task_success"] = False
        result = effects(raw, scored, cases)["candidate_research_dispositions"]
        knowledge = result["candidates"]["knowledge"]
        self.assertEqual(knowledge["disposition"], "fresh_evaluation_required")
        self.assertFalse(knowledge["strongest_control_saturated"])
        self.assertFalse(knowledge["use_as_selected_production_memory"])
        self.assertFalse(result["production_accepted"])

    def test_forged_contrast_or_citation_structure_fails_closed(self):
        raw, scored, cases = fixture()
        report = effects(raw, scored, cases)
        contrasts = report["contrasts"]
        stats = copy.deepcopy(report["structural_citations"])
        with self.assertRaises(ValueError):
            research_dispositions(
                {k: v for k, v in contrasts.items() if k != "knowledge_vs_hybrid"},
                stats,
                2,
            )
        stats["by_arm"]["knowledge"]["markers_without_any_sources"] = 2
        with self.assertRaises(ValueError):
            research_dispositions(contrasts, stats, 2)


if __name__ == "__main__":
    unittest.main()
