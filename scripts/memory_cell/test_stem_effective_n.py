"""Synthetic repeated-measures protection for 3 * 16 native held-out rows."""

from copy import deepcopy
import unittest

from stem_effective_n import effective_heldout_subjects
from stem_train_heldout_bridge import train_to_heldout_gap
from test_stem_train_heldout_bridge import fixture


def realistic_fixture():
    plan, learning, scored, targets = fixture()
    plan["question_families"] = {
        q: "native-family-" + q
        for ids in plan["questions"].values() for q in ids
    }
    paired = train_to_heldout_gap(plan, learning, scored, targets)
    return plan, paired


class UniqueHeldoutUnitsTests(unittest.TestCase):
    def test_three_checkpoints_do_not_triple_unique_test_subjects(self):
        plan, paired = realistic_fixture()
        result = effective_heldout_subjects(plan, paired)
        self.assertEqual(result["independent_question_ids_per_arm"], 16)
        self.assertEqual(result["repeated_question_evaluations_per_arm"], 48)
        self.assertEqual(len(result["by_arm"]), 5)
        each = result["by_arm"]["gated"]
        self.assertEqual(each["primary"]["planned_unique_questions"], 16)
        self.assertEqual(each["per_phase"]["test"]["planned_unique_questions"], 8)
        self.assertEqual(each["per_phase"]["transfer"]["planned_unique_questions"], 8)
        self.assertEqual(each["per_cell"]["general"]["planned_unique_questions"], 8)
        self.assertEqual(each["per_cell"]["temporal"]["planned_unique_questions"], 8)
        self.assertEqual(len(each["exploratory_all_three_checkpoint_subjects"]), 16)
        self.assertTrue(each["repeated_observations_must_not_be_48_independent_examples"])
        self.assertIsNone(each["variance_or_significance_from_nonindependent_questions"])
        self.assertFalse(each["independent_generalization_proven"])

    def test_frozen_matched_heldout_question_gain_not_tripled(self):
        plan, learning, scored, targets = fixture()
        plan["question_families"] = {
            q: "native-family-" + q
            for ids in plan["questions"].values() for q in ids
        }
        for stage in (16, 32, 48):
            candidate = next(row for row in scored
                             if row["stage"] == stage
                             and row["phase"] == "test"
                             and row["question_id"] == "test-0"
                             and row["arm"] == "gated")
            candidate.update(selected=1, source_choice_correct=1)
        paired = train_to_heldout_gap(plan, learning, scored, targets)
        report = effective_heldout_subjects(plan, paired)["by_arm"]["gated"]
        self.assertEqual(report["primary"]["source_support_gains"], 1)
        self.assertEqual(report["per_phase"]["test"]["source_support_gains"], 1)
        self.assertEqual(report["primary"]["source_support_scored_pairs"], 16)
        self.assertEqual(report["repeated_checkpoint_observations"], 48)
        self.assertTrue(report["exploratory_all_three_checkpoint_subjects"]["test-0"][
            "native_support_gain_on_all_three_stages"
        ])
        self.assertFalse(report["independent_generalization_proven"])

    def test_reader_failure_does_not_make_an_observation_independent(self):
        plan, learning, scored, targets = fixture()
        plan["question_families"] = {
            q: "native-family-" + q
            for ids in plan["questions"].values() for q in ids
        }
        learned = next(row for row in scored if row["stage"] == 48
                       and row["phase"] == "transfer"
                       and row["question_id"] == "transfer-2"
                       and row["arm"] == "gated")
        learned["status"] = "failed"
        learned.pop("diagnostic_answer_f1")
        paired = train_to_heldout_gap(plan, learning, scored, targets)
        report = effective_heldout_subjects(plan, paired)["by_arm"]["gated"]
        self.assertEqual(report["primary"]["planned_unique_questions"], 16)
        self.assertEqual(report["primary"]["paired_reader_f1_scored"], 15)
        self.assertEqual(
            report["primary"]["reader_f1_all_planned_bounds"],
            [-1 / 16, 1 / 16],
        )
        self.assertEqual(report["primary"]["source_support_scored_pairs"], 16)

    def test_original_natively_unanswerable_is_not_a_supported_source_gain(self):
        plan, learning, scored, targets = fixture()
        from dataclasses import replace
        targets["test-0"] = replace(targets["test-0"], unanswerable=True)
        plan["question_families"] = {
            q: "native-family-" + q
            for ids in plan["questions"].values() for q in ids
        }
        paired = train_to_heldout_gap(plan, learning, scored, targets)
        report = effective_heldout_subjects(plan, paired)["by_arm"]["gated"]["primary"]
        self.assertEqual(report["native_unanswerable_questions"], 1)
        self.assertEqual(report["source_support_scored_pairs"], 15)
        self.assertEqual(report["abstention_scored_pairs"], 1)
        self.assertEqual(report["source_support_gains"], 0)

    def test_duplicate_missing_cross_family_and_changed_category_fail(self):
        plan, paired = realistic_fixture()
        for scenario in ("duplicate", "missing", "family", "category", "phase"):
            candidate = deepcopy(paired)
            panel = candidate["test_transfer_paired_panel_rows"]
            if scenario == "duplicate":
                panel[-1] = deepcopy(panel[0])
            elif scenario == "missing":
                panel.pop()
            elif scenario == "family":
                panel[0]["source_family"] = "forged"
            elif scenario == "category":
                panel[0]["native_source_label_category"] = "native-unanswerable"
                panel[0]["native_answerable_source_support"] = False
                panel[0]["weak_support_gain"] = None
                panel[0]["native_abstention_gain"] = 0
            else:
                panel[0]["phase"] = "retention"
            with self.subTest(scenario=scenario), self.assertRaises(ValueError):
                effective_heldout_subjects(plan, candidate)

    def test_unresolved_cannot_claim_source_gain_and_failed_cannot_claim_f1(self):
        plan, paired = realistic_fixture()
        for scenario in ("unresolved", "reader"):
            candidate = deepcopy(paired)
            row = candidate["test_transfer_paired_panel_rows"][0]
            if scenario == "unresolved":
                row["native_source_label_category"] = "native-support-unresolved"
                row["native_answerable_source_support"] = False
            else:
                row["both_original_reader_calls_succeeded"] = False
            with self.subTest(scenario=scenario), self.assertRaises(ValueError):
                effective_heldout_subjects(plan, candidate)

    def test_unknown_test_names_and_forged_independence_are_rejected(self):
        plan, paired = realistic_fixture()
        for mode in ("question", "route", "schema"):
            p = deepcopy(plan)
            b = deepcopy(paired)
            if mode == "question":
                p["questions"]["test"][0] = "transfer-0"
            elif mode == "route":
                p["routes"]["test-0"] = "unregistered-cell"
            else:
                b["schema"] = "hepta.stem-train-heldout-diagnostic-gap.v2"
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                effective_heldout_subjects(p, b)


if __name__ == "__main__":
    unittest.main()
