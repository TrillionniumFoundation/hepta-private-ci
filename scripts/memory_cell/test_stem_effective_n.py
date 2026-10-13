"""Synthetic repeated-measures protection for 3 * 16 native held-out rows."""

from copy import deepcopy
import unittest

from stem_effective_n import effective_heldout_subjects
from stem_train_heldout_bridge import train_to_heldout_gap
from test_stem_train_heldout_bridge import fixture


def realistic_fixture():
    plan, learning, scored, targets = fixture()
    plan["question_families"] = {
        q: "native-family-" + q for ids in plan["questions"].values() for q in ids
    }
    paired = train_to_heldout_gap(plan, learning, scored, targets)
    return plan, paired


class UniqueHeldoutUnitsTests(unittest.TestCase):
    def test_previous_bridge_schema_cannot_sneak_into_v6_analysis(self):
        plan, bridge = realistic_fixture()
        self.assertEqual(bridge["schema"], "hepta.stem-train-heldout-diagnostic-gap.v6")
        bridge["schema"] = "hepta.stem-train-heldout-diagnostic-gap.v5"
        with self.assertRaisesRegex(ValueError, "unbound native held-out"):
            effective_heldout_subjects(plan, bridge)

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
        self.assertTrue(
            each["repeated_observations_must_not_be_48_independent_examples"]
        )
        self.assertIsNone(
            each["variance_or_significance_from_nonindependent_questions"]
        )
        self.assertFalse(each["independent_generalization_proven"])

    def test_frozen_matched_heldout_question_gain_not_tripled(self):
        plan, learning, scored, targets = fixture()
        plan["question_families"] = {
            q: "native-family-" + q for ids in plan["questions"].values() for q in ids
        }
        for stage in (16, 32, 48):
            candidate = next(
                row
                for row in scored
                if row["stage"] == stage
                and row["phase"] == "test"
                and row["question_id"] == "test-0"
                and row["arm"] == "gated"
            )
            candidate.update(selected=1, source_choice_correct=1)
        paired = train_to_heldout_gap(plan, learning, scored, targets)
        report = effective_heldout_subjects(plan, paired)["by_arm"]["gated"]
        self.assertEqual(report["primary"]["source_support_gains"], 1)
        self.assertEqual(report["per_phase"]["test"]["source_support_gains"], 1)
        self.assertEqual(report["primary"]["source_support_scored_pairs"], 16)
        self.assertEqual(report["repeated_checkpoint_observations"], 48)
        self.assertTrue(
            report["exploratory_all_three_checkpoint_subjects"]["test-0"][
                "native_support_gain_on_all_three_stages"
            ]
        )
        self.assertFalse(report["independent_generalization_proven"])

    def test_reader_failure_does_not_make_an_observation_independent(self):
        plan, learning, scored, targets = fixture()
        plan["question_families"] = {
            q: "native-family-" + q for ids in plan["questions"].values() for q in ids
        }
        learned = next(
            row
            for row in scored
            if row["stage"] == 48
            and row["phase"] == "transfer"
            and row["question_id"] == "transfer-2"
            and row["arm"] == "gated"
        )
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
            q: "native-family-" + q for ids in plan["questions"].values() for q in ids
        }
        paired = train_to_heldout_gap(plan, learning, scored, targets)
        report = effective_heldout_subjects(plan, paired)["by_arm"]["gated"]["primary"]
        self.assertEqual(report["native_unanswerable_questions"], 1)
        self.assertEqual(report["source_support_scored_pairs"], 15)
        self.assertEqual(report["abstention_scored_pairs"], 1)
        self.assertEqual(report["source_support_gains"], 0)

    def test_final_question_source_bounds_exclude_known_unanswerable_and_unresolved(self):
        from dataclasses import replace

        plan, learning, scored, targets = fixture()
        plan["question_families"] = {
            q: "native-family-" + q for ids in plan["questions"].values()
            for q in ids
        }
        targets["test-0"] = replace(targets["test-0"], unanswerable=True)
        targets["transfer-0"] = replace(
            targets["transfer-0"], evidence=(),
            unresolved_evidence=("missing-source",)
        )
        bridge = train_to_heldout_gap(plan, learning, scored, targets)
        final = bridge["final_checkpoint_unique_question_units"]["gated"]
        self.assertEqual(final["native_answerable_support_questions"], 14)
        self.assertEqual(final["native_unanswerable_questions"], 1)
        self.assertEqual(final["native_support_unresolved_questions"], 1)
        self.assertEqual(final["native_source_all_planned_net_gain_bounds"], [0, 0])
        report = effective_heldout_subjects(plan, bridge)
        primary = report["by_arm"]["gated"]["primary"]
        self.assertEqual(primary["source_support_answerable_only_bounds"], [0, 0])
        self.assertEqual(primary["abstention_native_unanswerable_only_bounds"], [0, 0])
        self.assertEqual(primary["source_support_all_planned_bounds"], [-1 / 8, 1 / 8])
        self.assertTrue(
            report["postpolicy_stratified_source_and_abstention_recomputed_from_panel"]
        )

    def test_known_native_abstention_does_not_inflate_source_missing_bounds(self):
        from dataclasses import replace

        plan, learning, scored, targets = fixture()
        plan["question_families"] = {
            q: "native-family-" + q for ids in plan["questions"].values()
            for q in ids
        }
        targets["test-0"] = replace(targets["test-0"], unanswerable=True)
        targets["transfer-0"] = replace(
            targets["transfer-0"], evidence=(),
            unresolved_evidence=("missing-source",)
        )
        for row in scored:
            if row["stage"] == 48 and row["question_id"] in ("test-0", "test-1"):
                row["source_choice_correct"] = None
        bridge = train_to_heldout_gap(plan, learning, scored, targets)
        result = effective_heldout_subjects(plan, bridge)
        primary = result["by_arm"]["gated"]["primary"]
        self.assertEqual(primary["answerable_native_source_questions"], 14)
        self.assertEqual(primary["source_support_scored_pairs"], 13)
        self.assertEqual(primary["source_support_answerable_only_bounds"], [-1 / 14, 1 / 14])
        self.assertEqual(primary["native_unanswerable_questions"], 1)
        self.assertEqual(primary["abstention_scored_pairs"], 0)
        self.assertEqual(primary["abstention_native_unanswerable_only_bounds"], [-1, 1])
        self.assertEqual(primary["unresolved_native_support_questions"], 1)
        self.assertEqual(primary["planned_unique_questions"], 16)

    def test_forged_final_stratified_receipts_are_rejected(self):
        plan, paired = realistic_fixture()
        for corruption, payload in (
            ("answerable", 17),
            ("source interval", [7, 7]),
            ("native abstention", 2),
            ("boolean masquerading as zero", False),
        ):
            altered = deepcopy(paired)
            final = altered["final_checkpoint_unique_question_units"]["gated"]
            if corruption == "answerable":
                final["native_answerable_support_questions"] = payload
            elif corruption == "source interval":
                final["native_source_all_planned_net_gain_bounds"] = payload
            elif corruption == "native abstention":
                final["native_unanswerable_questions"] = payload
            else:
                final["native_source_net_gain"] = payload
            with self.subTest(corruption=corruption), self.assertRaisesRegex(
                ValueError, "stratified native final question receipt"
            ):
                effective_heldout_subjects(plan, altered)

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

    def test_stable_frozen_pool_and_reader_must_match_across_checkpoints(self):
        for drift, replacement in (
            ("matched_original_pool_digest", "silently-changed-pool"),
            (
                "matched_reader_request_identity",
                ("same-model", "different-prompt", "wrong-request-hash"),
            ),
        ):
            plan, paired = realistic_fixture()
            row = next(
                x
                for x in paired["test_transfer_paired_panel_rows"]
                if x["stage"] == 32
                and x["arm"] == "gated"
                and x["question_id"] == "test-0"
            )
            row[drift] = replacement
            with (
                self.subTest(drift=drift),
                self.assertRaisesRegex(ValueError, "changed between checkpoints"),
            ):
                effective_heldout_subjects(plan, paired)

    def test_no_observed_selection_cannot_claim_old_pool_identity(self):
        plan, paired = realistic_fixture()
        row = paired["test_transfer_paired_panel_rows"][0]
        row["both_source_choices_observed"] = False
        row["changed_top1"] = None
        row["weak_support_gain"] = None
        with self.assertRaisesRegex(ValueError, "false pool binding"):
            effective_heldout_subjects(plan, paired)

    def test_failed_reader_pair_cannot_claim_verified_prompt(self):
        plan, paired = realistic_fixture()
        row = paired["test_transfer_paired_panel_rows"][0]
        row["both_original_reader_calls_succeeded"] = False
        row["both_reader_answers_scored"] = False
        row["diagnostic_answer_f1_delta"] = None
        with self.assertRaisesRegex(ValueError, "forged identity"):
            effective_heldout_subjects(plan, paired)

    def test_three_native_source_families_not_sixteen_independent_trials(self):
        plan, paired = realistic_fixture()
        test = plan["questions"]["test"]
        retention = plan["questions"]["retention"]
        transfer = plan["questions"]["transfer"]
        for q in test[:6] + retention[:6]:
            plan["question_families"][q] = "locomo:conv-47"
        for q in test[6:] + retention[6:]:
            plan["question_families"][q] = "locomo:conv-43"
        for q in transfer:
            plan["question_families"][q] = "longmemeval:001be529"
        for row in paired["test_transfer_paired_panel_rows"]:
            row["source_family"] = plan["question_families"][row["question_id"]]
        output = effective_heldout_subjects(plan, paired)
        cohort = output["original_native_source_family_structure"]
        self.assertEqual(cohort["test"], 2)
        self.assertEqual(cohort["transfer"], 1)
        self.assertEqual(cohort["combined_test_transfer"], 3)
        self.assertEqual(cohort["test_shared_with_retention"], 2)
        self.assertEqual(cohort["test_new_beyond_retention"], 0)
        self.assertFalse(cohort["test_is_unseen_source_family_vs_retention"])
        self.assertFalse(cohort["independent_family_sampling_verified"])
        self.assertEqual(output["independent_question_ids_per_arm"], 16)
        self.assertEqual(output["by_arm"]["gated"]["primary"]["source_family_count"], 3)

    def test_retention_overlap_does_not_require_gold_label_leakage(self):
        plan, paired = realistic_fixture()
        plan["question_families"]["retention-0"] = plan["question_families"]["test-0"]
        report = effective_heldout_subjects(plan, paired)
        family = report["original_native_source_family_structure"]
        self.assertEqual(family["test_shared_with_retention"], 1)
        self.assertEqual(family["test_new_beyond_retention"], 7)
        self.assertTrue(family["family_overlap_does_not_prove_training_label_leakage"])

    def test_unknown_original_family_in_retention_is_not_silently_ignored(self):
        plan, paired = realistic_fixture()
        plan["question_families"].pop("retention-0")
        with self.assertRaisesRegex(ValueError, "source-family lineage"):
            effective_heldout_subjects(plan, paired)

    def test_unknown_test_names_and_forged_independence_are_rejected(self):
        plan, paired = realistic_fixture()
        for mode in ("question", "route", "schema", "obsolete-v3"):
            p = deepcopy(plan)
            b = deepcopy(paired)
            if mode == "question":
                p["questions"]["test"][0] = "transfer-0"
            elif mode == "route":
                p["routes"]["test-0"] = "unregistered-cell"
            elif mode == "schema":
                b["schema"] = "hepta.stem-train-heldout-diagnostic-gap.v2"
            else:
                b["schema"] = "hepta.stem-train-heldout-diagnostic-gap.v3"
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                effective_heldout_subjects(p, b)


if __name__ == "__main__":
    unittest.main()
