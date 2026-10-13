"""Score-only question binding tests, not pretrained or independent evidence."""
from copy import deepcopy
import math
import unittest

from native import digest
from source_binding_specificity import question_binding


def fixture(*, adapter="bound"):
    a, b = "value_a", "value_b"
    cases = [
        dict(query=dict(identity="q1", scope="s"), scope="s", target=a, candidates=(a, b)),
        dict(query=dict(identity="q2", scope="s"), scope="s", target=b, candidates=(a, b)),
    ]
    rows = []
    for q in ("q1", "q2"):
        for arm in ("base", "memory"):
            for value in (a, b):
                loss = 1.0 if value == a else 3.0
                if arm == "memory":
                    if adapter == "bound":
                        loss = 0.5 if (q, value) in (("q1", a), ("q2", b)) else 3.0
                    else:
                        loss = 0.2 if value == a else 4.0
                rows.append(dict(
                    question_id=q, arm=arm, candidate_digest=digest(value),
                    scope="s", delivered_evidence=[], prompt_digest="prompt-" + q,
                    reader_profile="frozen-qwen",
                    actual_reader_question_id="paraphrase-" + q,
                    status="succeeded", mean_nll=loss, input_tokens=8,
                    supervised_tokens=2, seconds=0.1,
                ))
    return rows, cases


class QuestionBindingTests(unittest.TestCase):
    def test_true_query_conditioning_changes_cross_question_interaction(self):
        rows, cases = fixture()
        result = question_binding(rows, cases)
        self.assertEqual(result["complete_pairs"], 1)
        self.assertEqual(result["additional_model_calls"], 0)
        self.assertEqual(result["adapter_specificity_improved_pairs"], 1)
        self.assertEqual(result["new_dual_correct_pairs"], 1)
        self.assertAlmostEqual(result["pairs"][0]["frozen_specificity"], 0)
        self.assertAlmostEqual(result["pairs"][0]["adapter_specificity"], 2.5)
        self.assertFalse(result["production_accepted"])
        self.assertEqual(question_binding(list(reversed(rows)), cases), result)

    def test_global_identifier_prior_is_not_a_binding_gain(self):
        rows, cases = fixture(adapter="prior")
        result = question_binding(rows, cases)
        self.assertEqual(result["adapter_specificity_improved_pairs"], 0)
        self.assertEqual(result["new_dual_correct_pairs"], 0)
        self.assertAlmostEqual(result["pairs"][0]["adapter_minus_frozen"], 0)

    def test_missing_or_unequal_token_lengths_are_not_imputed(self):
        rows, cases = fixture()
        rows[0]["status"] = "failed"
        rows[0].pop("mean_nll")
        result = question_binding(rows, cases)
        self.assertEqual((result["failed_pairs"], result["complete_pairs"]), (1, 0))
        rows, cases = fixture()
        rows[0]["supervised_tokens"] = 3
        self.assertEqual(question_binding(rows, cases)["unequal_length_pairs"], 1)

    def test_different_targets_with_same_prompt_and_drift_rejected(self):
        rows, cases = fixture()
        for row in rows:
            row["prompt_digest"] = "same-input"
        with self.assertRaises(ValueError):
            question_binding(rows, cases)
        rows, cases = fixture()
        rows[0]["reader_profile"] = "other-model"
        with self.assertRaises(ValueError):
            question_binding(rows, cases)
        rows, cases = fixture()
        rows[0]["delivered_evidence"] = [{"source": "leak"}]
        with self.assertRaises(ValueError):
            question_binding(rows, cases)

    def test_original_unpaired_question_is_counted_not_discarded(self):
        rows, cases = fixture()
        only_one = question_binding(rows[:4], cases[:1])
        self.assertEqual(only_one["planned_pairs"], 0)
        self.assertEqual(only_one["unpaired_source_questions"], 1)
        self.assertEqual(len(only_one["unpaired_source_question_digests"]), 1)
        self.assertTrue(only_one["all_planned_questions_accounted"])
        self.assertFalse(only_one["statistical_superiority"])
        paired = question_binding(rows, cases)
        self.assertEqual(paired["unpaired_source_questions"], 0)
        self.assertEqual(paired["complete_pairs"], 1)

    def test_finite_nll_but_overflowing_adapter_delta_fails_closed(self):
        rows, cases = fixture()
        # Both individual nonnegative NLLs are finite. Each averaged
        # question/value margin is finite, but adapter-minus-base overflows.
        def set_loss(arm, qid, value, nll):
            for row in rows:
                if (row["arm"], row["question_id"], row["candidate_digest"]) == (
                    arm, qid, digest(value)
                ):
                    row["mean_nll"] = nll
                    return
            raise AssertionError("missing synthetic source candidate")

        base = 1e308
        for arm, reverse in (("base", True), ("memory", False)):
            for qid, true, false in (("q1", "value_a", "value_b"),
                                     ("q2", "value_b", "value_a")):
                set_loss(arm, qid, true, base if reverse else 0.0)
                set_loss(arm, qid, false, 0.0 if reverse else base)
        with self.assertRaisesRegex(ValueError, "nonfinite adapter-minus-frozen"):
            question_binding(rows, cases)

    def test_averaged_large_finite_margins_do_not_overflow(self):
        rows, cases = fixture()
        # A naive (left+right)/2 would overflow even though the true
        # average is finite and representable.
        for row in rows:
            if row["arm"] == "memory":
                is_correct = (row["question_id"], row["candidate_digest"]) in (
                    ("q1", digest("value_a")), ("q2", digest("value_b"))
                )
                row["mean_nll"] = 0.0 if is_correct else 1e308
        outcome = question_binding(rows, cases)
        self.assertEqual(outcome["complete_pairs"], 1)
        self.assertTrue(math.isfinite(outcome["pairs"][0]["adapter_minus_frozen"]))
        self.assertFalse(outcome["production_accepted"])

    def test_same_target_and_incomplete_census_are_not_positive(self):
        rows, cases = fixture()
        changed = deepcopy(cases)
        changed[1]["target"] = "value_a"
        result = question_binding(rows, changed)
        self.assertEqual(result["same_value_pairs"], 1)
        self.assertEqual(result["complete_pairs"], 0)
        with self.assertRaises(ValueError):
            question_binding(rows[:-1], cases)


if __name__ == "__main__":
    unittest.main()
