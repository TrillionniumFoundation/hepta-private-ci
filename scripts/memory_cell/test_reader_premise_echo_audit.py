"""Bounded, lexical-only adversarial echo diagnostics; no real Reader inference."""

import unittest

import reader_premise_echo_audit as audit


class ActualOutputBoundary(unittest.TestCase):
    def setUp(self):
        self.row = {
            "question": "What did Alice explain about the event?",
            "evidence": [
                {
                    "label": "E1",
                    "source_id": "D1:2",
                    "text": "Alice: A very long evidence source excerpt.",
                }
            ],
        }

    def response(self, text, **kwargs):
        return {
            "status": "succeeded",
            "answer": text,
            "input_tokens": kwargs.get("input_tokens", 140),
            "generated_tokens": kwargs.get("generated_tokens", 42),
        }

    def test_observed_json_prompt_echo_not_a_correctness_score(self):
        got = audit.characterize(
            self.row,
            self.response('{"question": "What did Alice explain about the event?"'),
        )
        self.assertTrue(got["json_prompt_echo_shape"])
        self.assertTrue(got["exact_question_repeated"])
        self.assertFalse(got["any_citation_marker"])

    def test_source_quotation_is_flag_only(self):
        got = audit.characterize(
            self.row, self.response("Alice: A very long evidence source excerpt.")
        )
        self.assertTrue(got["starts_with_evidence_source"])
        self.assertFalse(got["invalid_citation_marker"])

    def test_valid_and_invalid_citation_distinguished(self):
        self.assertTrue(
            audit.characterize(self.row, self.response("Answer [E1]"))[
                "all_emitted_markers_delivered"
            ]
        )
        got = audit.characterize(self.row, self.response("Answer [E2]"))
        self.assertTrue(got["invalid_citation_marker"])
        self.assertFalse(got["all_emitted_markers_delivered"])

    def test_budget_ceiling_is_observed_not_invented(self):
        got = audit.characterize(self.row, self.response("Answer", generated_tokens=48))
        self.assertTrue(got["hit_generation_ceiling"])
        with self.assertRaises(ValueError):
            audit.characterize(self.row, self.response("Answer", generated_tokens=49))

    def test_bad_absent_or_mismatched_result_is_denied(self):
        for bad in (
            {
                "status": "succeeded",
                "answer": "",
                "generated_tokens": 4,
                "input_tokens": 100,
            },
            {"status": "failed", "answer": "fabricated"},
            {"status": "completed", "answer": "something"},
            {
                "status": "succeeded",
                "answer": "x",
                "input_tokens": 0,
                "generated_tokens": 3,
            },
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                audit.characterize(self.row, bad)


if __name__ == "__main__":
    unittest.main()
