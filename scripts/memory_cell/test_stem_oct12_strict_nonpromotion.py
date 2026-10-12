"""Only immutable complete native evidence can produce a nonpromotion receipt."""

from copy import deepcopy
import unittest

from stem_oct12_strict_nonpromotion import (
    ARMS,
    confirm_sole_real_selection_flip,
    interpret_current,
)


def fixtures():
    gate = dict(
        schema="hepta.stem-native-nonpromotion-gate.v1",
        audited_policy_attempts=576,
        policy_execution_failures=0,
        citation_markers=0,
        production_accepted=False,
        scale_out_permitted=False,
        learning_arms={arm: {} for arm in ARMS},
    )
    exact = dict(
        schema="hepta.stem-strict-exact-paired-nonpromotion.v1",
        full_policy_attempts=576,
        exact_original_scored_receipt_matches=576,
        full_policy_execution_failures=0,
        raw_emitted_citation_markers=0,
        heldout_test_transfer_unique_questions=16,
        head_training_checkpoints=30,
        production_accepted=False,
        scale_out_permitted=False,
        learned_arms={
            arm: dict(
                matched_policy_pairs=96,
                changed_source_top1=1 if arm == "lineage_lora_gated" else 0,
                changed_original_answer_bytes=0,
                weak_native_support_gains=0,
                weak_native_support_regressions=0,
            )
            for arm in ARMS
        },
    )
    panel = dict(
        schema="hepta.stem-effective-heldout-repeated-panel.v3",
        independent_question_ids_per_arm=16,
        repeated_question_evaluations_per_arm=48,
        source_family_sampling_independence_certified=False,
        production_accepted=False,
    )
    return gate, exact, panel


class NewStrictRejectionTests(unittest.TestCase):
    def test_no_learned_gain_is_explicit_rejection_not_success(self):
        verdict = interpret_current(*fixtures())
        self.assertEqual(verdict["complete_original_policy_attempts"], 576)
        self.assertEqual(verdict["failed_policy_attempts"], 0)
        self.assertEqual(
            verdict["independent_test_transfer_question_units_per_arm"], 16
        )
        self.assertTrue(verdict["no_observed_learner_vs_frozen_correct_decision_gain"])
        self.assertTrue(verdict["exactly_one_real_selection_flip_with_no_support_gain"])
        self.assertEqual(
            verdict["learned_arms"]["lineage_lora_gated"]["changed_top1"], 1
        )
        self.assertIsNone(verdict["semantic_citation_precision"])
        self.assertFalse(verdict["scale_out_permitted"])
        self.assertFalse(verdict["production_accepted"])

    def test_any_incomplete_native_or_head_count_is_rejected(self):
        for part, field, value in (
            (0, "audited_policy_attempts", 575),
            (0, "policy_execution_failures", 1),
            (1, "full_policy_attempts", 575),
            (1, "head_training_checkpoints", 29),
            (2, "independent_question_ids_per_arm", 48),
            (2, "repeated_question_evaluations_per_arm", 16),
        ):
            original = fixtures()
            docs = list(deepcopy(original))
            docs[part][field] = value
            with self.subTest(part=part, field=field), self.assertRaises(ValueError):
                interpret_current(*docs)

    def test_citation_marker_or_forged_admission_fails_closed(self):
        for part, field, value in (
            (0, "citation_markers", 1),
            (1, "raw_emitted_citation_markers", 1),
            (0, "production_accepted", True),
            (1, "scale_out_permitted", True),
            (2, "source_family_sampling_independence_certified", True),
        ):
            docs = list(deepcopy(fixtures()))
            docs[part][field] = value
            with self.subTest(part=part, field=field), self.assertRaises(ValueError):
                interpret_current(*docs)

    def test_one_learned_changed_selection_is_not_hidden(self):
        docs = list(fixtures())
        docs[1]["learned_arms"]["gated"]["changed_source_top1"] = 1
        with self.assertRaises(ValueError):
            interpret_current(*docs)

    def test_one_learned_changed_answer_is_not_hidden(self):
        docs = list(fixtures())
        docs[1]["learned_arms"]["linear"]["changed_original_answer_bytes"] = 1
        with self.assertRaises(ValueError):
            interpret_current(*docs)

    def test_native_support_imbalances_are_not_zero_gain(self):
        docs = list(fixtures())
        docs[1]["learned_arms"]["prototype"]["weak_native_support_gains"] = 1
        docs[1]["learned_arms"]["prototype"]["weak_native_support_regressions"] = 1
        with self.assertRaises(ValueError):
            interpret_current(*docs)

    def test_extra_missing_or_drifting_arm_rejected(self):
        for corruption in ("drop", "add"):
            docs = list(deepcopy(fixtures()))
            if corruption == "drop":
                del docs[0]["learning_arms"]["gated"]
            else:
                docs[1]["learned_arms"]["unregistered"] = {}
            with self.subTest(corruption=corruption), self.assertRaises(ValueError):
                interpret_current(*docs)


def native_policy_fixture():
    phases = ("select", "retention", "test", "transfer")
    arms = ("frozen_rerank", *ARMS)
    records, judged = [], []
    for stage in (16, 32, 48):
        for phase in phases:
            questions = (
                ["locomo:conv-43/q217", *[f"retention-{i}" for i in range(7)]]
                if phase == "retention"
                else [f"{phase}-{i}" for i in range(8)]
            )
            for question in questions:
                for arm in arms:
                    selected = (
                        7
                        if (stage, phase, question, arm)
                        == (
                            48,
                            "retention",
                            "locomo:conv-43/q217",
                            "lineage_lora_gated",
                        )
                        else 1
                    )
                    record = dict(
                        stage=stage,
                        phase=phase,
                        question_id=question,
                        arm=arm,
                        selected=selected,
                        pool_digest="immutable-pool-" + question,
                        family="family-" + question,
                        cell="general",
                        answer="Same frozen Reader answer.",
                        receipt=dict(
                            generator_identity="reader-pin",
                            generator_profile="reader-prompt-pin",
                        ),
                    )
                    records.append(record)
                    judged.append(
                        dict(
                            stage=stage,
                            phase=phase,
                            question_id=question,
                            arm=arm,
                            source_choice_correct=0,
                        )
                    )
    return records, judged


class ExactChangedDecisionTests(unittest.TestCase):
    def test_only_real_retention_difference_kept_but_not_promoted(self):
        raw, judged = native_policy_fixture()
        changes = confirm_sole_real_selection_flip({}, raw, judged)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["frozen_selected"], 1)
        self.assertEqual(changes[0]["learned_selected"], 7)
        self.assertEqual(changes[0]["learned_weak_native_support"], 0)
        self.assertFalse(changes[0]["answer_bytes_changed"])

    def test_tampered_extra_flip_and_forged_support_fail_closed(self):
        for corruption in ("extra", "support", "answer", "missing"):
            raw, judged = native_policy_fixture()
            altered = next(
                row
                for row in raw
                if row["stage"] == 48
                and row["phase"] == "retention"
                and row["question_id"] == "locomo:conv-43/q217"
                and row["arm"] == "lineage_lora_gated"
            )
            if corruption == "extra":
                extra = next(
                    row
                    for row in raw
                    if row["stage"] == 16
                    and row["phase"] == "test"
                    and row["arm"] == "gated"
                )
                extra["selected"] = 3
            elif corruption == "support":
                evidence = next(
                    row
                    for row in judged
                    if row["stage"] == 48
                    and row["phase"] == "retention"
                    and row["question_id"] == "locomo:conv-43/q217"
                    and row["arm"] == "lineage_lora_gated"
                )
                evidence["source_choice_correct"] = 1
            elif corruption == "answer":
                altered["answer"] = "Counterfactual generated change."
            else:
                raw.pop()
            with self.subTest(corruption=corruption), self.assertRaises(ValueError):
                confirm_sole_real_selection_flip({}, raw, judged)


if __name__ == "__main__":
    unittest.main()
