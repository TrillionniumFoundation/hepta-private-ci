"""Development-only unit controls; these are NOT pretrained Qwen generations."""

from copy import deepcopy
from types import SimpleNamespace
import unittest

from locomo_publisher_format_trial import (
    FORMAT_PROFILE,
    REFUSAL,
    STRICT_SYSTEM,
    format_input,
    paired_result,
    plan_zip_bytes,
)
from locomo_publisher_completion_receipt import EXPECTED, refusal_shape
from native import digest


class MockTokenizer:
    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
        assert tokenize and add_generation_prompt
        self.messages = messages
        return list(range(len(messages[0]["content"] + messages[1]["content"]) // 12 + 1))


class FormatTests(unittest.TestCase):
    def test_same_source_and_question_bytes_in_strict_input(self):
        tok = MockTokenizer()
        q = SimpleNamespace(content="When did 雨 move?", observed_at="2026-10-01T12:00:00Z")
        src = [dict(label="E1", observed_at="2026-09-12T12:00:00Z", excerpt="雨 moved to Kyoto")]
        ids = format_input(tok, q, src, 2048)
        self.assertTrue(ids)
        self.assertEqual(tok.messages[0]["content"], STRICT_SYSTEM)
        self.assertIn('"text": "雨 moved to Kyoto"', tok.messages[1]["content"])
        self.assertIn('"question": "When did 雨 move?"', tok.messages[1]["content"])
        self.assertNotIn("answer_key", tok.messages[1]["content"])
        self.assertEqual(FORMAT_PROFILE, "strict-answer-or-refusal-citation.v1")

    def test_strict_prompt_budget_rejects_instead_of_truncation(self):
        with self.assertRaises(ValueError):
            format_input(MockTokenizer(), SimpleNamespace(content="q", observed_at="t"), [], 1024)
        with self.assertRaises(ValueError):
            format_input(MockTokenizer(), SimpleNamespace(content="z" * 35000, observed_at="t"), [], 2048)

    def test_historical_plan_is_externally_byte_pinned(self):
        self.assertEqual(len(EXPECTED["plan"]), 64)

    @staticmethod
    def fixture(*, new_answer="correct [E1]", new_status="succeeded"):
        cases, admitted, rows, old, targets = [], [], [], [], {}
        for i in range(16):
            qid = f"q{i}"
            family = "a" if i < 8 else "b"
            cases.append(dict(
                question_id=qid,
                family_proxy_digest=family,
                source_census_sha256="source",
            ))
            admitted.append(dict(mode="publisher_support", selected=["doc1"]))
            r = dict(
                question_id=qid,
                mode="publisher_support",
                selected=["doc1"],
                family_proxy_digest=family,
                source_census_sha256="source",
                status=new_status,
                answer=new_answer,
                receipt=dict(
                    input_tokens=85,
                    delivered_evidence=[dict(label="E1")],
                ),
            )
            rows.append(r)
            old.append(dict(
                question_id=qid,
                status="succeeded",
                selected=["doc1"],
                answer="incorrect [E1]",
                receipt=dict(input_tokens=65),
            ))
            targets[qid] = dict(unanswerable=False, answer="correct")
        return cases, admitted, rows, old, targets

    def test_answer_quality_and_refusal_are_separate_from_citation_syntax(self):
        data = self.fixture()
        score = paired_result(*data)
        self.assertEqual(score["comparison"]["all"]["planned"], 16)
        self.assertEqual(score["comparison"]["all"]["wins"], 16)
        self.assertIsNone(score["semantic_citation_precision"])
        self.assertFalse(score["production_accepted"])
        self.assertEqual(score["comparison"]["all"]["strict_citation_markers"], 16)

    def test_mixed_refusal_is_not_counted_as_safe(self):
        d = list(self.fixture(new_answer=REFUSAL + " guessed [E9]"))
        score = paired_result(*d)
        self.assertEqual(score["comparison"]["all"]["strict_mixed_refusals"], 16)
        self.assertEqual(score["comparison"]["all"]["strict_answers_with_undelivered_labels"], 16)
        self.assertEqual(refusal_shape(REFUSAL), "strict_refusal")

    def test_failed_generation_keeps_original_denominator(self):
        d = list(self.fixture())
        d[2][0]["status"] = "failed"
        d[2][0].pop("answer")
        result = paired_result(*d)["comparison"]["all"]
        self.assertEqual(result["planned"], 16)
        self.assertEqual(result["complete"], 15)
        self.assertEqual(result["missing_or_unscored"], 1)
        self.assertEqual(result["all_planned_delta_bounds"], [(15 - 1) / 16, 1.0])

    def test_candidate_change_rejected_not_better_accuracy(self):
        d = list(self.fixture())
        d[2][0]["selected"] = ["different"]
        with self.assertRaises(ValueError):
            paired_result(*d)

    def test_duplicate_original_question_cannot_pass(self):
        d = list(self.fixture())
        d[3][1]["question_id"] = d[3][0]["question_id"]
        with self.assertRaises(ValueError):
            paired_result(*d)


if __name__ == "__main__":
    unittest.main()
