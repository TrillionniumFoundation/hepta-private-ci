"""Small authored fixtures exercise audit rejection, not model performance."""

from copy import deepcopy
import unittest

from masked_span_audit import check_census, check_same_input_outputs
from selector_answering import ARMS


class SpanExecutionAuditTests(unittest.TestCase):
    def records(self):
        return [
            dict(
                phase="squad_test", question_id="question", arm=arm,
                status="succeeded", answer="original",
                receipt=dict(
                    generator_identity="model", generator_profile="profile",
                    input_ids_digest="input", generated_ids_digest="output",
                ),
            )
            for arm in ARMS
        ]

    def test_complete_census_and_label_enrichment_preserve_original_answer(self):
        raw = self.records()
        scored = [dict(row, f1=0.5) for row in raw]
        plan = dict(questions=dict(train=["training"], select=["selection"], squad_test=["question"]))
        self.assertEqual(len(check_census(raw, scored, plan)), 6)
        self.assertEqual(check_same_input_outputs(raw), 1)
        for damaged in (raw[:-1], raw + [raw[0]], [dict(r, question_id="other") for r in raw]):
            with self.assertRaises(ValueError):
                check_census(damaged, scored, plan)

    def test_scoring_cannot_rewrite_answers_or_generation_receipts(self):
        raw = self.records()
        plan = dict(questions=dict(squad_test=["question"]))
        for key, value in (("answer", "corrected"), ("receipt", {}), ("status", "failed")):
            changed = deepcopy(raw)
            changed[0][key] = value
            with self.assertRaises(ValueError):
                check_census(raw, changed, plan)

    def test_identical_model_inputs_cannot_depend_on_arm_identity(self):
        raw = self.records()
        raw[1]["answer"] = "different"
        with self.assertRaises(ValueError):
            check_same_input_outputs(raw)
        raw[1]["receipt"]["input_ids_digest"] = "different-input"
        self.assertEqual(check_same_input_outputs(raw), 2)


if __name__ == "__main__":
    unittest.main()
