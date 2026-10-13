"""Citation instruction controls use authored fixtures, not new Qwen outputs."""

import copy
from dataclasses import dataclass
import json
import unittest

from event_citation_prompt_trial import (
    CONDITIONS,
    STYLES,
    PREMISE_APPENDIX,
    premise_prompt,
    score_one,
    summarize,
)


@dataclass(frozen=True)
class FakeQuestion:
    content: str = "Which site was recorded?"
    observed_at: str = "2026-10-13T00:00:00Z"


class FakeTokenizer:
    def __init__(self):
        self.messages = None

    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
        self.messages = messages
        assert tokenize and add_generation_prompt
        return list(
            range(
                1,
                1
                + len(messages[0]["content"].split())
                + len(messages[1]["content"].split()),
            )
        )


def fixture():
    receipt = dict(
        reader_identity="pinned",
        input_ids_digest="original",
        delivered_evidence=[
            dict(
                label="E1",
                original_id="d1",
                excerpt="The input is updated.",
                observed_at="now",
            ),
            dict(
                label="E2",
                original_id="d2",
                excerpt="The output is site_11223344.",
                observed_at="now",
            ),
        ],
        derived_evidence=[dict(label="E1", text="schema relation")],
    )
    truth = dict(kind="composition", expected="site_11223344", support=["d1", "d2"])
    return receipt, truth


def row(style, answer, *, receipt=None, status="succeeded"):
    default, _ = fixture()
    return dict(
        question_id="q1",
        kind="composition",
        condition="organized",
        style=style,
        selected=["d1", "d2"],
        candidate_digest="pool",
        status=status,
        answer=answer,
        receipt=copy.deepcopy(receipt or default),
    )


class PromptTests(unittest.TestCase):
    def test_same_user_question_and_exact_supplied_payload_not_support_labels(self):
        receipt, truth = fixture()
        tokenizer = FakeTokenizer()
        ids = premise_prompt(tokenizer, FakeQuestion(), receipt, token_limit=2048)
        self.assertGreater(len(ids), 10)
        user = json.loads(tokenizer.messages[1]["content"])
        self.assertEqual(user["question"], FakeQuestion.content)
        self.assertEqual(user["evidence"][0]["text"], "The input is updated.")
        self.assertEqual(
            user["controlled_schema_expansions"], receipt["derived_evidence"]
        )
        self.assertNotIn("support", user)
        self.assertNotIn("expected", user)
        self.assertNotIn(truth["expected"], tokenizer.messages[0]["content"])
        self.assertIn(PREMISE_APPENDIX, tokenizer.messages[0]["content"])

    def test_all_labelled_premises_are_required_for_complete_chain(self):
        receipt, truth = fixture()
        partial = score_one(
            row("original", "site_11223344 [E2]", receipt=receipt), truth
        )
        complete = score_one(
            row("premise_chain", "site_11223344 [E1] [E2]", receipt=receipt), truth
        )
        self.assertTrue(partial["strict_task_success"])
        self.assertFalse(partial["complete_citation_chain"])
        self.assertEqual(partial["required_delivered_but_uncited"], ["d1"])
        self.assertTrue(complete["strict_success_and_complete_chain"])
        self.assertEqual(complete["required_delivered_but_uncited"], [])

    def test_hallucinated_citation_is_not_delivered_or_semantically_certified(self):
        receipt, truth = fixture()
        scored = score_one(
            row("original", "site_11223344 [E2] [E7]", receipt=receipt), truth
        )
        self.assertEqual(scored["unbound_label_occurrences"], ["E7"])
        self.assertFalse(scored["complete_citation_chain"])
        self.assertTrue(scored["formal_requirements_are_not_human_verified"])
        invented = score_one(
            row("premise_chain", "site_11223344 [E1] [E2] [E7]", receipt=receipt),
            truth,
        )
        self.assertEqual(invented["unbound_label_occurrences"], ["E7"])
        self.assertFalse(invented["complete_citation_chain"])

    def test_missing_prerequisite_remains_a_delivery_failure(self):
        receipt, truth = fixture()
        receipt["delivered_evidence"] = receipt["delivered_evidence"][1:]
        sample = row("original", "site_11223344 [E2]", receipt=receipt)
        sample["selected"] = ["d2"]
        scored = score_one(sample, truth)
        self.assertFalse(scored["required_delivered"])
        self.assertEqual(scored["required_undelivered"], ["d1"])

    def test_complete_pairs_do_not_mistake_citation_gain_for_task_gain(self):
        receipt, truth = fixture()
        a = score_one(row("original", "site_11223344 [E2]", receipt=receipt), truth)
        b = row("premise_chain", "site_11223344 [E1] [E2]", receipt=receipt)
        b["receipt"]["input_ids_digest"] = "changed"
        b = score_one(b, truth)
        records = []
        # Keep all four original arrangements, including authored privileged cases.
        for condition in CONDITIONS:
            for style, example in zip(STYLES, (a, b), strict=True):
                sample = copy.deepcopy(example)
                sample["condition"] = condition
                records.append(sample)
        result = summarize(records, {"q1": {"query": {"identity": "q1"}}})
        for part in result["by_condition"].values():
            self.assertEqual(part["original_strict_correct"], 1)
            self.assertEqual(part["premise_prompt_strict_correct"], 1)
            self.assertEqual(part["original_strict_and_complete_formal_chain"], 0)
            self.assertEqual(part["premise_prompt_strict_and_complete_formal_chain"], 1)
            self.assertEqual((part["task_wins"], part["task_losses"]), (0, 0))
        self.assertIsNone(result["independent_semantic_citation_precision"])

    def test_incomplete_or_drifted_pairs_refuse_summary(self):
        receipt, truth = fixture()
        a = score_one(row("original", "site_11223344 [E2]", receipt=receipt), truth)
        b = row("premise_chain", "site_11223344 [E1] [E2]", receipt=receipt)
        b["receipt"]["input_ids_digest"] = "changed"
        b = score_one(b, truth)
        records = []
        for condition in CONDITIONS:
            for example in (a, b):
                sample = copy.deepcopy(example)
                sample["condition"] = condition
                records.append(sample)
        with self.assertRaises(ValueError):
            summarize(records[:-1], {"q1": {}})
        records[1]["receipt"]["delivered_evidence"][0]["excerpt"] = "tampered"
        with self.assertRaises(ValueError):
            summarize(records, {"q1": {}})

    def test_failed_calls_keep_full_denominator_and_no_success(self):
        receipt, truth = fixture()
        a = score_one(row("original", "site_11223344 [E2]", receipt=receipt), truth)
        b = score_one(row("premise_chain", "", status="failed"), truth)
        records = []
        for condition in CONDITIONS:
            for example in (a, b):
                sample = copy.deepcopy(example)
                sample["condition"] = condition
                records.append(sample)
        report = summarize(records, {"q1": {}})
        self.assertTrue(
            all(x["missing_pairs"] == 1 for x in report["by_condition"].values())
        )
        self.assertTrue(
            all(
                x["all_planned_task_effect_bounds"] == [-1, 1]
                for x in report["by_condition"].values()
            )
        )


if __name__ == "__main__":
    unittest.main()
