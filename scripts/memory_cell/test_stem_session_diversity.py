"""Session-diverse control uses true session metadata, not trust-root aliases."""

import unittest
from types import SimpleNamespace

from sessions import source_id
from stem_frozen_retrieval_grid import BASELINE, label_key, validate_unlabelled
from stem_session_diversity import (
    compare_session_diversity,
    session_distinct,
    validate_session_receipts,
)
from test_stem_frozen_retrieval_grid import fixture


def setup():
    plan, raw, labels = fixture()
    for row in raw:
        if row["policy"] == label_key(BASELINE):
            row["retrieved_source_ids"] = ["source-distractor", "source-duplicate"]
            row["window_source_ids"] = ["source-distractor"]
    original = validate_unlabelled(plan, raw)
    observations = []
    for phase in plan["questions"]:
        for qid in plan["questions"][phase]:
            first = original[(phase, qid, label_key(BASELINE))]
            ranked = [
                {"id": "source-distractor", "root": "one", "session": "s1"},
                {"id": "source-duplicate", "root": "one", "session": "s1"},
                {"id": "source-positive", "root": "one", "session": "s2"},
            ]
            selected = session_distinct(ranked, 2)
            observations.append(
                dict(
                    phase=phase,
                    question_id=qid,
                    source_family=first["source_family"],
                    original_as_of_index_sha256=first["original_as_of_index_sha256"],
                    original_baseline_source_ids=first["retrieved_source_ids"],
                    ranked_original_source_sessions=ranked,
                    selected_original_identities=selected,
                    retrieved_source_ids=list(map(source_id, selected)),
                    window_source_ids=list(map(source_id, selected)),
                    pool_sha256="a" * 64,
                    source_text_exported=False,
                    read_targets_for_retrieval=False,
                    pretrained_reader_calls=0,
                )
            )
    return plan, original, observations, labels


class SessionDiversityTests(unittest.TestCase):
    def test_same_trust_root_different_sessions_expand_coverage(self):
        ranked = [
            {"id": "a", "root": "same", "session": "one"},
            {"id": "b", "root": "same", "session": "one"},
            {"id": "c", "root": "same", "session": "two"},
            {"id": "d", "root": "same", "session": "three"},
        ]
        self.assertEqual(session_distinct(ranked, 2), ["a", "c"])
        self.assertEqual(session_distinct(ranked, 3), ["a", "c", "d"])
        self.assertEqual(session_distinct(ranked, 4), ["a", "c", "d", "b"])

    def test_malformed_metadata_and_unknown_groups_fail_closed(self):
        for ranked in (
            [{"id": "x", "root": "root", "session": ""}],
            [{"id": "x", "root": "root"}],
            [{"id": "x", "root": "root", "session": "s", "answer": "gold"}],
            [{"id": "x", "root": "r", "session": "s"}] * 2,
        ):
            with self.subTest(ranked=ranked), self.assertRaises(ValueError):
                session_distinct(ranked, 1)
        with self.assertRaises(ValueError):
            session_distinct([{"id": "a", "root": "r", "session": "s"}], 9)

    def test_80_question_census_and_source_only_diagnostic(self):
        plan, original, rows, labels = setup()
        actual = validate_session_receipts(plan, original, rows)
        report = compare_session_diversity(plan, original, actual, labels)
        self.assertEqual(len(actual), 80)
        self.assertEqual(report["results"]["test"]["planned"], 8)
        self.assertEqual(report["results"]["test"]["document_rescues"], 8)
        self.assertTrue(report["diversifies_document_session_not_withdrawal_root"])
        self.assertFalse(report["product_answer_gain_not_measured"] is False)
        self.assertIsNone(report["semantic_citation_precision"])

    def test_unchanged_session_ranking_does_not_claim_improvement(self):
        plan, original, rows, labels = setup()
        for row in rows:
            row["ranked_original_source_sessions"][1]["session"] = "s2"
            row["ranked_original_source_sessions"][2]["session"] = "s3"
            row["selected_original_identities"] = [
                "source-distractor",
                "source-duplicate",
            ]
            row["retrieved_source_ids"] = ["source-distractor", "source-duplicate"]
            # The original window is the distractor. The synthetic setup's
            # previous diversified window was sourced from "source-positive",
            # which is no longer in the unchanged top-K selection.
            row["window_source_ids"] = ["source-distractor"]
            # No-change control must retain only its baseline delivered window.
            row["window_source_ids"] = ["source-distractor"]
        outcomes = validate_session_receipts(plan, original, rows)
        result = compare_session_diversity(plan, original, outcomes, labels)
        self.assertEqual(result["results"]["test"]["document_rescues"], 0)
        self.assertEqual(result["results"]["test"]["changed_source_topk"], 0)

    def test_no_question_reordering_or_model_input_replacement(self):
        for change in ("index", "rank", "choice", "pool", "window", "answer", "family"):
            plan, original, rows, _ = setup()
            if change == "index":
                rows[0]["original_as_of_index_sha256"] = "other"
            elif change == "rank":
                rows[0]["ranked_original_source_sessions"][0]["id"] = "changed"
            elif change == "choice":
                rows[0]["selected_original_identities"] = [
                    "source-positive",
                    "source-distractor",
                ]
            elif change == "pool":
                rows[0]["pool_sha256"] = ""
            elif change == "window":
                rows[0]["window_source_ids"] = ["unselected-document"]
            elif change == "answer":
                rows[0]["read_targets_for_retrieval"] = True
            else:
                rows[0]["source_family"] = "invented"
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_session_receipts(plan, original, rows)

    def test_duplicate_and_missing_native_tasks_reject(self):
        plan, original, rows, targets = setup()
        for bad in (rows[:-1], rows[:-1] + [rows[0]]):
            with self.assertRaises(ValueError):
                validate_session_receipts(plan, original, bad)
        observed = validate_session_receipts(plan, original, rows)
        with self.assertRaises(ValueError):
            compare_session_diversity(
                plan,
                original,
                observed,
                {q: v for q, v in targets.items() if q != "test-0"},
            )

    def test_native_unknown_is_not_accepted_as_negative(self):
        plan, original, rows, targets = setup()
        targets["test-0"] = SimpleNamespace(
            unanswerable=True, unresolved_evidence=(), evidence=()
        )
        observed = validate_session_receipts(plan, original, rows)
        report = compare_session_diversity(plan, original, observed, targets)
        self.assertEqual(report["results"]["test"]["unscored_native_label"], 1)
        self.assertFalse(report["production_accepted"])


if __name__ == "__main__":
    unittest.main()
