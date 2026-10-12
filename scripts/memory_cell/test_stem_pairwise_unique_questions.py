"""Synthetic pairwise Shadow question deduplication, no benchmark gold."""

import unittest

from stem_pairwise_unique_questions import unique_shadow_question_bounds

PHASES = ("select", "retention", "test", "transfer")
ARMS = ("pairwise_linear", "pairwise_gated")
STAGES = (16, 32, 48)


def fixture():
    questions = {"train": [f"train-{i}" for i in range(48)]}
    questions.update({phase: [f"{phase}-{i}" for i in range(8)]
                      for phase in PHASES})
    plan = dict(questions=questions)
    choices = []
    groups = {}
    for stage in STAGES:
        for phase in PHASES:
            for arm in ARMS:
                groups[f"{stage}/{phase}/{arm}"] = dict(
                    attempted=8, selection_changed=0,
                    native_weak_support_gains=0,
                    native_weak_support_regressions=0,
                )
                for qid in questions[phase]:
                    choices.append(dict(
                        stage=stage, phase=phase, question_id=qid, arm=arm,
                        family="family-" + qid, status="succeeded",
                        original_frozen_selected=0, selected=0,
                        candidate_count=8, actual_reader_calls=0,
                    ))
    posthoc = dict(
        schema="hepta.stem-pairwise-native-source-only-shadow.v1",
        by_checkpoint_phase_arm=groups,
        production_accepted=False,
        independently_established_generalization=False,
    )
    return plan, choices, posthoc


def flip(choices, posthoc, stage, phase, qid, arm, *, gain=0, regression=0):
    row = next(x for x in choices if
               (x["stage"], x["phase"], x["question_id"], x["arm"])
               == (stage, phase, qid, arm))
    if row["selected"] == row["original_frozen_selected"]:
        row["selected"] = 1
        posthoc["by_checkpoint_phase_arm"][
            f"{stage}/{phase}/{arm}"
        ]["selection_changed"] += 1
    slot = posthoc["by_checkpoint_phase_arm"][f"{stage}/{phase}/{arm}"]
    slot["native_weak_support_gains"] += gain
    slot["native_weak_support_regressions"] += regression


def repeated_fixture():
    plan, choices, posthoc = fixture()
    # 19 events, 5 unique questions, 4 source families across phases.
    for stage in STAGES:
        for arm in ARMS:
            flip(choices, posthoc, stage, "retention", "retention-0", arm)
    for stage in (32, 48):
        for arm in ARMS:
            flip(choices, posthoc, stage, "transfer", "transfer-0", arm)
            flip(choices, posthoc, stage, "test", "test-0", arm, gain=1)
    for stage in (32, 48):
        for arm in ARMS:
            flip(choices, posthoc, stage, "select", "select-1", arm)
    flip(choices, posthoc, 32, "select", "select-0", "pairwise_linear",
         gain=1)
    return plan, choices, posthoc


class UniqueQuestionAuditTests(unittest.TestCase):
    def test_zero_flips_are_not_a_positive_effect(self):
        plan, choices, posthoc = fixture()
        x = unique_shadow_question_bounds(plan, choices, posthoc)
        self.assertEqual(x["distinct_changed_question_count"], 0)
        self.assertEqual(x["distinct_question_gain_bounds"], [0, 0])
        self.assertFalse(x["independent_source_family_generalization_proven"])

    def test_nineteen_events_five_questions_but_two_possible_unique_gains(self):
        plan, choices, posthoc = repeated_fixture()
        r = unique_shadow_question_bounds(plan, choices, posthoc)
        self.assertEqual(r["original_shadow_decision_count"], 192)
        self.assertEqual(r["repeated_rank_flip_events"], 19)
        self.assertEqual(r["distinct_changed_question_count"], 5)
        self.assertEqual(r["weak_document_source_gain_events"], 5)
        self.assertEqual(r["distinct_question_gain_bounds"], [2, 2])
        self.assertEqual(r["exact_distinct_question_gain_count"], 2)
        self.assertEqual(r["distinct_test_transfer_question_gain_bounds"], [1, 1])
        self.assertEqual(r["per_phase"]["test"]["changed_unique_questions"], 1)
        self.assertEqual(r["per_phase"]["test"]["weak_gain_events"], 4)
        self.assertEqual(r["per_phase"]["transfer"]["weak_gain_events"], 0)
        self.assertEqual(len(r["changed_question_review_worklist"]), 5)
        self.assertTrue(all(
            x["weak_source_gain_attributable_to_this_question"] is None
            for x in r["changed_question_review_worklist"]
        ))

    def test_ambiguous_group_gains_stay_bounds_not_fabricated_gold(self):
        plan, choices, posthoc = fixture()
        flip(choices, posthoc, 32, "select", "select-0", "pairwise_linear")
        flip(choices, posthoc, 32, "select", "select-1", "pairwise_linear",
             gain=1)
        flip(choices, posthoc, 48, "select", "select-1", "pairwise_linear",
             gain=1)
        r = unique_shadow_question_bounds(plan, choices, posthoc)
        self.assertEqual(r["per_phase"]["select"]["unique_weak_gain_question_bounds"],
                         [1, 2])
        self.assertIsNone(r["exact_distinct_question_gain_count"])

    def test_cannot_promote_repeated_checkpoint_gains_to_four_questions(self):
        plan, choices, posthoc = fixture()
        for stage in (32, 48):
            for arm in ARMS:
                flip(choices, posthoc, stage, "test", "test-0", arm, gain=1)
        r = unique_shadow_question_bounds(plan, choices, posthoc)
        self.assertEqual(r["per_phase"]["test"]["weak_gain_events"], 4)
        self.assertEqual(r["per_phase"]["test"]["exact_unique_weak_gain_count"], 1)

    def test_missing_duplicate_or_unregistered_shadow_fails(self):
        for mode in ("missing", "duplicate", "unregistered"):
            p, rows, audit = fixture()
            if mode == "missing":
                rows.pop()
            elif mode == "duplicate":
                rows[-1] = dict(rows[0])
            else:
                rows[0]["question_id"] = "not-preregistered"
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                unique_shadow_question_bounds(p, rows, audit)

    def test_invalid_gain_and_reader_calls_cannot_be_laundered(self):
        for mode in ("too-many-gains", "reader-call", "production"):
            p, rows, audit = fixture()
            if mode == "too-many-gains":
                audit["by_checkpoint_phase_arm"][
                    "16/test/pairwise_linear"
                ]["native_weak_support_gains"] = 1
            elif mode == "reader-call":
                rows[0]["actual_reader_calls"] = 1
            else:
                audit["production_accepted"] = True
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                unique_shadow_question_bounds(p, rows, audit)

    def test_source_family_drift_and_duplicate_question_ids_reject(self):
        p, rows, audit = fixture()
        rows[0]["family"] = "other"
        with self.assertRaisesRegex(ValueError, "source family"):
            unique_shadow_question_bounds(p, rows, audit)
        p, rows, audit = fixture()
        p["questions"]["test"][0] = p["questions"]["select"][0]
        with self.assertRaises(ValueError):
            unique_shadow_question_bounds(p, rows, audit)


if __name__ == "__main__":
    unittest.main()
