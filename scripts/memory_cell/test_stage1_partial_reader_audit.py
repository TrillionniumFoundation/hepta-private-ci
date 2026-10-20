"""Fail-closed cancellation accounting on fixed original-prefix fixtures."""

import copy
import math
import unittest
from stage1_reader_score import answer_scores
from stage1_partial_reader_audit import evaluate_prefix


def fixture():
    cases, original, labels, partial = [], {}, {}, []
    for index in range(8):
        qid = f"q{index}"
        evidence = [{"label": "E1", "excerpt": f"answer {index}"}]
        cases.append(
            {
                "question": {"identity": qid},
                "family": f"group-{index}",
                "phase": "capability",
                "conditions": {
                    "retrieved1": {"delivered_evidence": evidence},
                    "empty": {"delivered_evidence": []},
                },
            }
        )
        labels[qid] = {"answer": f"answer {index}", "unanswerable": False}
        for arm in ("retrieved1", "empty"):
            row = {
                "question_id": qid,
                "arm": arm,
                "family": f"group-{index}",
                "phase": "capability",
                "status": "succeeded",
                "answer": f"answer {index}",
                "receipt": {
                    "delivered_evidence": copy.deepcopy(
                        evidence if arm == "retrieved1" else []
                    )
                },
            }
            row.update(answer_scores(row["answer"], (labels[qid]["answer"],), False))
            original[(qid, arm)] = row
    partial.append(
        {
            "question_id": "q0",
            "arm": "retrieved1",
            "family": "group-0",
            "phase": "capability",
            "status": "succeeded",
            "answer": "answer 0",
            "receipt": {
                "delivered_evidence": copy.deepcopy(
                    cases[0]["conditions"]["retrieved1"]["delivered_evidence"]
                ),
                "reader_identity": "distinct-reference-model",
                "trainable_parameters": 0,
                "answer_postprocessed": False,
                "seconds": 12.5,
                "generated_tokens": 5,
            },
        }
    )
    return {"cases": cases}, partial, original, labels


class CancelledReaderCensusTests(unittest.TestCase):
    def run_fixture(self, plan, partial, original, labels):
        return evaluate_prefix(
            plan,
            partial,
            original,
            labels,
            reference_identity="distinct-reference-model",
        )

    def test_full_denominator_and_missing_outcome_bounds(self):
        plan, partial, original, labels = fixture()
        result = self.run_fixture(plan, partial, original, labels)
        self.assertEqual(result["planned"], 16)
        self.assertEqual(result["durable_prefix"], 1)
        self.assertEqual(result["not_attempted"], 15)
        self.assertEqual(result["actually_paired"], 1)
        self.assertEqual(result["full_planned_delta_lower_bound"], -15 / 16)
        self.assertEqual(result["full_planned_delta_upper_bound"], 15 / 16)
        self.assertFalse(result["capacity_superiority_established"])
        self.assertFalse(result["production_accepted"])

    def test_no_posthoc_reordered_selection(self):
        plan, partial, original, labels = fixture()
        partial[0]["arm"] = "empty"
        with self.assertRaisesRegex(ValueError, "untouched original prefix"):
            self.run_fixture(plan, partial, original, labels)

    def test_source_mismatch_is_not_reader_gain(self):
        plan, partial, original, labels = fixture()
        partial[0]["receipt"]["delivered_evidence"] = []
        with self.assertRaisesRegex(ValueError, "evidence differs"):
            self.run_fixture(plan, partial, original, labels)

    def test_failed_or_unavailable_not_scored(self):
        plan, partial, original, labels = fixture()
        partial[0]["status"] = "unavailable"
        with self.assertRaisesRegex(ValueError, "unexecuted model answer"):
            self.run_fixture(plan, partial, original, labels)
        partial[0].pop("answer")
        partial[0].pop("receipt")
        result = self.run_fixture(plan, partial, original, labels)
        self.assertEqual(result["actual_unavailable"], 1)
        self.assertEqual(result["actually_paired"], 0)
        self.assertEqual(result["unpaired_or_not_attempted"], 16)

    def test_nonfinite_seconds_and_optimizer_rejected(self):
        for field, value in (("seconds", math.nan), ("trainable_parameters", 8)):
            plan, partial, original, labels = fixture()
            partial[0]["receipt"][field] = value
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(ValueError, "actual reference inference"),
            ):
                self.run_fixture(plan, partial, original, labels)

    def test_original_baseline_score_cannot_be_rewritten(self):
        plan, partial, original, labels = fixture()
        original[("q0", "retrieved1")]["f1"] = 0.3
        with self.assertRaisesRegex(ValueError, "original baseline scorer drift"):
            self.run_fixture(plan, partial, original, labels)


if __name__ == "__main__":
    unittest.main()
