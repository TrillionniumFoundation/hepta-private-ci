"""Synthetic comparative census tests; historic ZIP pins are separately checked."""

from copy import deepcopy
import unittest

from stem_archive_contrast import (
    ARMS,
    PHASES,
    STAGES,
    REGISTRATION_KEYS,
    index_census,
    candidate_distribution,
    compare_receipts,
)
from stem_audit_archive import AuditError


def fixtures():
    questions = {"train": [f"train-{n}" for n in range(48)]}
    questions.update({phase: [f"{phase}-{n}" for n in range(8)] for phase in PHASES})
    plan = {key: "frozen-fixture" for key in REGISTRATION_KEYS}
    plan.update(
        arms=list(ARMS),
        curriculum_attempted_examples=list(STAGES),
        questions=questions,
        source_commit="fixture",
    )
    rows, legacy = [], []
    for stage in STAGES:
        for phase in PHASES:
            for qid in questions[phase]:
                for arm in ARMS:
                    key = dict(
                        stage=stage,
                        phase=phase,
                        question_id=qid,
                        family="family-fixture",
                        arm=arm,
                        selected=0,
                    )
                    receipt = dict(
                        generator_identity="reader",
                        generator_profile="prompt",
                        delivered_evidence=[{"label": "E1"}],
                        input_ids_digest="tokens",
                        generated_ids_digest="original-output",
                    )
                    legacy.append(
                        dict(
                            key,
                            status="succeeded",
                            answer="Unchanged.",
                            receipt=deepcopy(receipt),
                        )
                    )
                    rows.append(
                        dict(
                            key,
                            status="succeeded",
                            answer="Unchanged.",
                            receipt=deepcopy(receipt),
                        )
                    )
    for row in rows[:180]:
        row.update(status="failed", error_type="ValueError")
        row.pop("answer")
        row.pop("receipt")
    encoded = [
        dict(
            backend="frozen",
            question_id=q,
            cost=dict(
                cache_hit=False,
                extraction=dict(
                    pairs=32 if phase == "transfer" else 8,
                ),
            ),
        )
        for phase, qs in questions.items()
        for q in qs
    ]
    return plan, rows, deepcopy(plan), legacy, encoded


class HistoricalContrastTests(unittest.TestCase):
    def test_exact_fixed_576_attempt_census(self):
        original_plan, original, _, _, _ = fixtures()
        indexed = index_census(original_plan, original)
        self.assertEqual(len(indexed), 576)
        self.assertEqual(
            sum(row["status"] == "failed" for row in indexed.values()), 180
        )

    def test_previously_successful_raw_answer_kept_and_no_gain(self):
        original_plan, original, legacy_plan, legacy, encoding = fixtures()
        result = compare_receipts(
            original_plan, original, legacy_plan, legacy, encoding
        )
        self.assertEqual(result["identical_old_success_answers_and_reader_inputs"], 396)
        self.assertEqual(result["legacy_status"]["succeeded"], 576)
        self.assertFalse(result["production_accepted"])
        self.assertFalse(result["legacy_canonical_reader_admission_validated"])
        self.assertTrue(
            all(
                x["changed_source_selection"] == 0
                and x["changed_original_answer_bytes"] == 0
                for x in result["legacy_learned_arms"].values()
            )
        )

    def test_same_source_different_answer_cannot_be_called_preserved(self):
        plan_a, old, plan_b, new, encodings = fixtures()
        new[181]["answer"] = "Invented after old generation."
        with self.assertRaisesRegex(AuditError, "rewritten"):
            compare_receipts(plan_a, old, plan_b, new, encodings)

    def test_preserved_success_request_digest_mismatch_is_a_hard_failure(self):
        plan_a, old, plan_b, new, encodings = fixtures()
        new[181]["receipt"]["input_ids_digest"] = "tampered"
        with self.assertRaisesRegex(AuditError, "rewritten"):
            compare_receipts(plan_a, old, plan_b, new, encodings)

    def test_duplicate_missing_and_nonregistered_arm_fail_closed(self):
        p, old, _, _, _ = fixtures()
        for damaged in (
            old[:-1],
            old[:-1] + [old[0]],
            old[:-1] + [dict(old[-1], arm="new_fake_arm")],
        ):
            with self.assertRaises(AuditError):
                index_census(p, damaged)

    def test_original_question_and_model_registration_pins_cannot_drift(self):
        p, old, p2, newer, encodings = fixtures()
        p2["reader_inventory"] = "other-reader"
        with self.assertRaisesRegex(AuditError, "registration drift"):
            compare_receipts(p, old, p2, newer, encodings)

    def test_candidate_histogram_and_missing_frozen_question(self):
        p, old, p2, newer, enc = fixtures()
        x = candidate_distribution(p, enc)
        self.assertEqual(x["train"]["competing_candidate_pools"], 48)
        self.assertEqual(x["transfer"]["histogram"], {"32": 8})
        self.assertEqual(x["select"]["one_candidate"], 0)
        with self.assertRaisesRegex(AuditError, "missing frozen"):
            candidate_distribution(p, enc[:-1])

    def test_changed_policy_selection_in_previous_failure_is_disclosed(self):
        plan_a, original, plan_b, newer, encodings = fixtures()
        original[0]["selected"] = 1
        result = compare_receipts(plan_a, original, plan_b, newer, encodings)
        self.assertEqual(result["cross_run_selection_change_count"], 1)
        self.assertEqual(result["identical_old_success_answers_and_reader_inputs"], 396)
        self.assertTrue(
            all(
                not x["learned_benefit_independently_demonstrated"]
                for x in result["legacy_learned_arms"].values()
            )
        )


if __name__ == "__main__":
    unittest.main()
