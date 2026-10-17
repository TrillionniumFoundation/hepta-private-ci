"""Frozen published LoCoMo cost-frontier regressions, not Reader quality tests."""

import copy
import json
from pathlib import Path
import unittest

from locomo_budget_frontier import (
    ARMS,
    audit_frontier,
    verified_original_report_bytes,
)


PINNED = Path(__file__).parent / "data" / "locomo-ninearm-offline-20261012.json"


def original():
    return json.loads(PINNED.read_bytes())


class BudgetFrontierTests(unittest.TestCase):
    def test_exact_published_original_nine_arms_are_bound(self):
        report = audit_frontier(original())
        self.assertEqual(len(report["evaluation"]), 9)
        self.assertEqual(set(report["evaluation"]), set(ARMS))
        self.assertEqual(
            report["selected_policy_from_original_selection_cut"], "lexical_k8"
        )
        x = report["preexisting_fixed_budget_comparison"]
        self.assertEqual(x["net_annotated_support_coverage_difference"], 1)
        self.assertEqual(x["extra_delivered_utf8_source_bytes"], 8449)
        self.assertTrue(x["posthoc_selection_of_new_policy_prohibited"])
        self.assertTrue(report["no_new_source_reader_calls"])
        self.assertFalse(report["production_accepted"])

    def test_exact_committed_original_byte_pin_rejects_rewrites(self):
        raw = PINNED.read_bytes()
        self.assertEqual(len(verified_original_report_bytes(raw)), 64)
        for modified in (raw + b" ", raw.replace(b"lexical_k8", b"lexical_k4", 1)):
            with (
                self.subTest(size=len(modified)),
                self.assertRaisesRegex(ValueError, "blob pin drift"),
            ):
                verified_original_report_bytes(modified)

    def test_posthoc_frontier_does_not_choose_a_new_policy(self):
        out = audit_frontier(original())
        self.assertEqual(
            out["posthoc_evaluation_pareto_frontier"],
            ["lexical_k2", "lexical_k4", "lexical_k8", "fusion_k2"],
        )
        self.assertTrue(out["dominated_by"]["fusion_k4"])
        self.assertTrue(out["dominated_by"]["fusion_k8"])
        self.assertTrue(out["dominated_by"]["recent_k8"])
        self.assertEqual(
            out["evaluation"]["lexical_k4"]["annotated_full_source_support_covered"], 8
        )
        self.assertEqual(
            out["evaluation"]["lexical_k8"]["annotated_full_source_support_covered"], 9
        )
        self.assertTrue(out["delivered_source_bytes_are_not_reader_input_tokens"])
        self.assertTrue(out["end_to_end_reader_p95_dollars_energy_not_measured"])

    def test_forged_heldout_benefit_breaks_family_census(self):
        report = original()
        report["evaluation"]["fusion_k8"]["full_annotated_support_covered"] += 2
        with self.assertRaisesRegex(ValueError, "family proxy"):
            audit_frontier(report)

    def test_forged_missing_outcome_bounds_are_rejected(self):
        report = original()
        report["evaluation"]["lexical_k8"]["missing_outcome_lower"] = 1.0
        with self.assertRaisesRegex(ValueError, "missing-outcome bounds"):
            audit_frontier(report)

    def test_unqualified_model_citation_or_source_promotion_rejected(self):
        for name, val in (
            ("models_generated", 1),
            ("citation_entailment_precision", 1.0),
            ("production_accepted", True),
            ("independent_source_family_authentication", True),
            ("selected_arm", "lexical_k4"),
            ("original_six_arm_replay_agrees", False),
        ):
            with self.subTest(name=name):
                report = original()
                report[name] = val
                with self.assertRaisesRegex(ValueError, "unqualified"):
                    audit_frontier(report)

    def test_missing_or_fake_arm_and_negative_bytes_rejected(self):
        for mode in ("arm", "cost"):
            report = original()
            if mode == "arm":
                report["evaluation"]["new_gated_lora"] = copy.deepcopy(
                    report["evaluation"]["lexical_k8"]
                )
            else:
                report["evaluation"]["lexical_k8"]["selected_source_bytes"] = -1
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                audit_frontier(report)

    def test_missing_and_unresolved_questions_not_silently_dropped(self):
        report = original()
        report["evaluation"]["lexical_k8"]["eligible"] = 16
        report["evaluation"]["lexical_k8"]["unknown_or_unanswerable"] = 0
        with self.assertRaisesRegex(ValueError, "census"):
            audit_frontier(report)

    def test_two_family_summary_must_match_eligible_counts(self):
        report = original()
        family = next(iter(report["evaluation"]["lexical_k4"]["per_family"]))
        report["evaluation"]["lexical_k4"]["per_family"][family]["eligible"] = 100
        with self.assertRaisesRegex(ValueError, "family proxy"):
            audit_frontier(report)


if __name__ == "__main__":
    unittest.main()
