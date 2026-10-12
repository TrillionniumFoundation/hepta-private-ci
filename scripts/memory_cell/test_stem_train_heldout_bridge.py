"""Synthetic complete 576-case bridge; no native benchmark gains are fabricated."""

import unittest

from native import Target
from stem_train_heldout_bridge import train_to_heldout_gap

ARMS = (
    "frozen_rerank",
    "prototype",
    "linear",
    "gated",
    "lineage_lora_gated",
    "independent_lora_gated",
)
STAGES = (16, 32, 48)
PHASES = ("select", "retention", "test", "transfer")
CELLS = ("general", "temporal")


def fixture():
    questions = {"train": [f"train-{i}" for i in range(48)]}
    questions.update({phase: [f"{phase}-{i}" for i in range(8)] for phase in PHASES})
    routes = {
        q: CELLS[i % 2] for group in questions.values() for i, q in enumerate(group)
    }
    plan = dict(
        questions=questions,
        routes=routes,
        arms=list(ARMS),
        curriculum_attempted_examples=list(STAGES),
        cells=list(CELLS),
    )
    scored = []
    for stage in STAGES:
        for phase in PHASES:
            for qid in questions[phase]:
                for arm in ARMS:
                    scored.append(
                        dict(
                            stage=stage,
                            phase=phase,
                            question_id=qid,
                            arm=arm,
                            status="succeeded",
                            cell=routes[qid],
                            family="native-family-" + qid,
                            selected=0,
                            pool_digest="sealed-" + qid,
                            source_choice_correct=0,
                            diagnostic_answer_f1=0.25,
                            answer="fixture answer",
                            receipt=dict(
                                generator_identity="pinned-reader",
                                generator_profile="pinned-reader-prompt",
                            delivered_evidence=[dict(
                                original_id="source-"+qid,
                                label="E1", excerpt="fixture source"
                            )],
                                observable_query=dict(
                                    identity=qid,
                                    content="Fixture question.",
                                    observed_at="2024-01-01",
                                    scope="scope-" + qid,
                                ),
                            ),
                        )
                    )
    learning = []
    for stage in STAGES:
        for arm in ARMS:
            for cell in CELLS:
                h = dict(
                    stage=stage,
                    arm=arm,
                    cell=cell,
                    status="succeeded",
                    before_sha256="a" * 64,
                    after_sha256="b" * 64,
                )
                if arm != "frozen_rerank":
                    h["within_train_fit_dynamics"] = dict(
                        checkpoint=stage,
                        arm=arm,
                        cell=cell,
                        previous_head_sha256=h["before_sha256"],
                        updated_head_sha256=h["after_sha256"],
                        heldout_annotations_consulted=False,
                        independent_generalization_established=False,
                        production_accepted=False,
                        mean_weak_loss_delta=-0.4,
                        weak_source_top1_gains=1,
                        mean_positive_over_negative_candidate_margin_delta=2.0,
                    )
                learning.append(h)
    targets = {
        q: Target("fixture answer", "fixture", ("native-source-" + q,), False)
        for phase in PHASES
        for q in questions[phase]
    }
    return plan, learning, scored, targets


class GeneralizationBridgeTests(unittest.TestCase):
    def test_complete_census_preserves_training_vs_test_distinction(self):
        plan, learning, scored, targets = fixture()
        result = train_to_heldout_gap(plan, learning, scored, targets)
        self.assertEqual(result["planned_source_policy_rows"], 576)
        self.assertEqual(len(result["by_checkpoint_cell_arm"]), 30)
        arm = result["by_checkpoint_cell_arm"]["48/gated/general"]
        self.assertLess(arm["within_head_train_mean_weak_loss_delta"], 0)
        self.assertEqual(arm["phases"]["test"]["planned"], 4)
        self.assertEqual(arm["phases"]["transfer"]["planned"], 4)
        self.assertTrue(arm["train_fit_but_no_heldout_native_source_net_gain"])
        self.assertFalse(arm["authentic_independent_generalization"])
        self.assertFalse(result["production_accepted"])

    def test_one_heldout_supported_selection_gain_is_not_fabricated_for_other_arms(
        self,
    ):
        plan, learning, scored, targets = fixture()
        changed = next(
            row
            for row in scored
            if row["stage"] == 48
            and row["phase"] == "test"
            and row["question_id"] == "test-0"
            and row["arm"] == "gated"
        )
        changed["selected"] = 1
        changed["source_choice_correct"] = 1
        changed["diagnostic_answer_f1"] = 0.75
        result = train_to_heldout_gap(plan, learning, scored, targets)
        gated = result["by_checkpoint_cell_arm"]["48/gated/general"]
        self.assertEqual(gated["phases"]["test"]["native_support_gains"], 1)
        self.assertEqual(gated["phases"]["test"]["source_decision_changes"], 1)
        self.assertAlmostEqual(
            gated["phases"]["test"]["paired_reader_f1_delta_mean"], 0.125
        )
        self.assertFalse(gated["train_fit_but_no_heldout_native_source_net_gain"])
        other = result["by_checkpoint_cell_arm"]["48/linear/general"]
        self.assertEqual(other["phases"]["test"]["native_support_gains"], 0)
        self.assertFalse(gated["authentic_independent_generalization"])

    def test_reader_failure_does_not_erase_observed_selector_choice(self):
        plan, learning, scored, targets = fixture()
        x = next(
            row
            for row in scored
            if row["stage"] == 48
            and row["phase"] == "test"
            and row["question_id"] == "test-0"
            and row["arm"] == "gated"
        )
        x["status"] = "failed"
        x.pop("diagnostic_answer_f1")
        x["source_choice_correct"] = 1
        x["selected"] = 1
        result = train_to_heldout_gap(plan, learning, scored, targets)
        summary = result["by_checkpoint_cell_arm"]["48/gated/general"]["phases"]["test"]
        self.assertEqual(summary["source_compared"], 4)
        self.assertEqual(summary["native_support_gains"], 1)
        self.assertEqual(summary["reader_f1_scored"], 3)
        self.assertEqual(summary["reader_f1_unscored"], 1)
        self.assertEqual(summary["all_planned_reader_f1_delta_bounds"], [-0.25, 0.25])

    def test_unresolved_native_support_keeps_original_question_in_denominator(self):
        plan, learning, scored, targets = fixture()
        for row in scored:
            if (row["stage"], row["phase"], row["question_id"]) == (
                48,
                "transfer",
                "transfer-0",
            ):
                row["source_choice_correct"] = None
        result = train_to_heldout_gap(plan, learning, scored, targets)
        summary = result["by_checkpoint_cell_arm"]["48/gated/general"]["phases"][
            "transfer"
        ]
        self.assertEqual(summary["planned"], 4)
        self.assertEqual(summary["source_compared"], 3)
        self.assertEqual(summary["source_unresolved_or_unselected"], 1)

    def test_missing_answerable_heldout_source_comparison_is_inconclusive(self):
        plan, learning, scored, targets = fixture()
        for row in scored:
            if (row["stage"], row["phase"], row["question_id"]) == (
                48, "transfer", "transfer-0"
            ):
                row.pop("selected", None)
                row.pop("pool_digest", None)
        report = train_to_heldout_gap(plan, learning, scored, targets)
        current = report["by_checkpoint_cell_arm"]["48/gated/general"]
        self.assertFalse(current["heldout_source_comparison_complete"])
        self.assertIsNone(current["train_fit_but_no_heldout_native_source_net_gain"])
        self.assertLess(
            current["heldout_answerable_source_scored"],
            current["heldout_answerable_source_planned"],
        )

    def test_retrieval_pool_identity_and_family_mismatch_fail(self):
        for field, value in (
            ("pool_digest", "changed-pool"),
            ("family", "wrong-family"),
            ("cell", "opposite-cell"),
        ):
            plan, learning, scored, targets = fixture()
            candidate = next(
                x
                for x in scored
                if x["stage"] == 16
                and x["phase"] == "test"
                and x["question_id"] == "test-0"
                and x["arm"] == "gated"
            )
            candidate[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                train_to_heldout_gap(plan, learning, scored, targets)

    def test_final_checkpoint_repeated_questions_are_not_48_independent_cases(self):
        plan, learning, scored, targets = fixture()
        out = train_to_heldout_gap(plan, learning, scored, targets)
        arm = out["final_checkpoint_unique_question_units"]["gated"]
        self.assertEqual(arm["unique_test_transfer_questions"], 16)
        self.assertEqual(arm["training_checkpoint_repeats_per_question"], 3)
        self.assertEqual(arm["observed_source_support_pairs"], 16)
        self.assertEqual(arm["native_source_net_gain"], 0)
        self.assertEqual(arm["native_source_all_planned_net_gain_bounds"], [0, 0])
        self.assertTrue(arm["confidence_interval_not_claimed"])

    def test_missing_evaluable_source_pair_keeps_conservative_unique_bounds(self):
        plan, learning, scored, targets = fixture()
        for row in scored:
            if (row["stage"], row["phase"], row["question_id"]) == (
                48,
                "test",
                "test-0",
            ):
                row["source_choice_correct"] = None
        out = train_to_heldout_gap(plan, learning, scored, targets)
        arm = out["final_checkpoint_unique_question_units"]["gated"]
        self.assertEqual(arm["observed_source_support_pairs"], 15)
        self.assertEqual(arm["native_source_all_planned_net_gain_bounds"], [-1, 1])
        self.assertEqual(arm["unique_test_transfer_questions"], 16)

    def test_missing_or_duplicate_policy_or_head_fails_closed(self):
        for corruption in ("missing-policy", "duplicate-policy", "missing-head"):
            plan, learning, scored, targets = fixture()
            if corruption == "missing-policy":
                scored.pop()
            elif corruption == "duplicate-policy":
                scored[-1] = dict(scored[0])
            else:
                learning.pop()
            with self.subTest(corruption=corruption), self.assertRaises(ValueError):
                train_to_heldout_gap(plan, learning, scored, targets)

    def test_native_unanswerable_does_not_count_as_source_gain(self):
        plan, learning, scored, targets = fixture()
        targets["test-0"] = Target(None, "native-abs", (), True)
        result = train_to_heldout_gap(plan, learning, scored, targets)
        test = result["by_checkpoint_cell_arm"]["48/gated/general"]["phases"]["test"]
        self.assertEqual(test["planned"], 4)
        self.assertEqual(test["native_unanswerable_rows"], 1)
        self.assertEqual(test["answerable_native_document_support_rows"], 3)
        self.assertEqual(test["source_compared"], 3)
        self.assertEqual(test["observed_native_abstention_pairs"], 1)
        self.assertEqual(test["native_support_gains"], 0)
        self.assertEqual(test["native_abstention_gains"], 0)
        self.assertTrue(result["native_document_support_vs_abstention_separate"])

    def test_forged_abstention_correctness_is_rejected(self):
        plan, learning, scored, targets = fixture()
        targets["test-0"] = Target(None, "native-abs", (), True)
        learned = next(
            x
            for x in scored
            if x["stage"] == 48
            and x["phase"] == "test"
            and x["question_id"] == "test-0"
            and x["arm"] == "gated"
        )
        learned["source_choice_correct"] = 1
        with self.assertRaisesRegex(ValueError, "abstention label"):
            train_to_heldout_gap(plan, learning, scored, targets)

    def test_unresolved_support_remains_in_original_planned_denominator(self):
        plan, learning, scored, targets = fixture()
        targets["transfer-0"] = Target(
            "answer", "fixture", (), False, ("unresolved-source",)
        )
        result = train_to_heldout_gap(plan, learning, scored, targets)
        transfer = result["by_checkpoint_cell_arm"]["48/gated/general"]["phases"][
            "transfer"
        ]
        self.assertEqual(transfer["planned"], 4)
        self.assertEqual(transfer["native_support_unresolved_rows"], 1)
        self.assertEqual(transfer["source_compared"], 3)
        self.assertEqual(transfer["source_unresolved_or_unselected"], 1)

    def test_missing_or_invalid_target_metadata_is_not_admitted(self):
        plan, learning, scored, targets = fixture()
        targets.pop("test-0")
        with self.assertRaisesRegex(ValueError, "32 post-policy"):
            train_to_heldout_gap(plan, learning, scored, targets)
        targets["test-0"] = object()
        with self.assertRaises((ValueError, AttributeError)):
            train_to_heldout_gap(plan, learning, scored, targets)

    def test_reader_model_prompt_and_observable_question_must_match(self):
        for drift, key in (
            ("changed-reader", "generator_identity"),
            ("changed-prompt", "generator_profile"),
            ("wrong-question", "observable_query"),
        ):
            plan, learning, scored, targets = fixture()
            learned = next(
                x
                for x in scored
                if x["stage"] == 48
                and x["phase"] == "test"
                and x["question_id"] == "test-0"
                and x["arm"] == "gated"
            )
            if drift == "wrong-question":
                learned["receipt"][key]["identity"] = "test-1"
            else:
                learned["receipt"][key] = drift
            with (
                self.subTest(drift=drift),
                self.assertRaisesRegex(ValueError, "Reader model/prompt/query"),
            ):
                train_to_heldout_gap(plan, learning, scored, targets)

    def test_identical_top1_requires_identical_delivered_evidence(self):
        plan, learning, scored, targets = fixture()
        learned = next(
            row for row in scored
            if row["stage"] == 48 and row["phase"] == "test"
            and row["question_id"] == "test-0" and row["arm"] == "gated"
        )
        learned["receipt"]["delivered_evidence"][0]["excerpt"] = "different source"
        with self.assertRaisesRegex(ValueError, "unchanged top-1"):
            train_to_heldout_gap(plan, learning, scored, targets)

    def test_changed_selection_allows_distinct_bound_reader_sources(self):
        plan, learning, scored, targets = fixture()
        learned = next(
            row for row in scored
            if row["stage"] == 48 and row["phase"] == "test"
            and row["question_id"] == "test-0" and row["arm"] == "gated"
        )
        learned["selected"] = 1
        learned["receipt"]["delivered_evidence"][0]["original_id"] = "other-source"
        result = train_to_heldout_gap(plan, learning, scored, targets)
        phase = result["by_checkpoint_cell_arm"]["48/gated/general"]["phases"]["test"]
        self.assertEqual(phase["source_decision_changes"], 1)
        self.assertFalse(result["production_accepted"])

    def test_head_sha_or_hidden_heldout_annotation_claim_is_rejected(self):
        for corruption in ("sha", "label"):
            plan, learning, scored, targets = fixture()
            head = next(x for x in learning if x["arm"] == "gated")
            probe = head["within_train_fit_dynamics"]
            if corruption == "sha":
                probe["previous_head_sha256"] = "c" * 64
            else:
                probe["heldout_annotations_consulted"] = True
            with (
                self.subTest(corruption=corruption),
                self.assertRaisesRegex(ValueError, "TRAIN-only"),
            ):
                train_to_heldout_gap(plan, learning, scored, targets)


if __name__ == "__main__":
    unittest.main()
