"""Matched-generator mocks are contract tests, not pretrained-model results."""

from copy import deepcopy
from dataclasses import replace
import unittest

import torch

from native import Document, Question
from selector_head import EvidenceHead, Features
from selector_windows import candidate_windows
from selector_answering import ARMS, choose, paired_generate, selected_window
from selector_answer_metrics import answer_scores, matched_report


class Generator:
    def __init__(self):
        self.calls = []

    def answer(self, query, sources, *, revoked):
        self.calls.append((query, sources))
        return "independent generated text [E1]", dict(
            generator_identity="test-only",
            generator_profile="fixed",
            delivered_evidence=list(sources),
        )


def example():
    query = Question("q", "f", "scope", "What happened?", "2024")
    doc = Document("d", "root", "scope", "session", "2023", "Old event. " * 70)
    pool = candidate_windows((doc,), query, revoked=set())
    f = Features(
        query.identity,
        "f",
        "test",
        pool.seal(),
        tuple(w.identity() for w in pool.windows),
        frozenset(["root"]),
        torch.ones(len(pool.windows), 3),
        -torch.ones(len(pool.windows)),
    )
    return query, pool, f, EvidenceHead(3, "test")


class AnsweringTests(unittest.TestCase):
    def records(self):
        q, pool, f, h = example()
        g = Generator()
        rows = paired_generate(
            q, "f", pool, f, h, g, dict(frozen=0, trained=0), revoked=set()
        )
        for r in rows:
            r.update(phase="test", f1=0.0, exact_match=0.0)
        return rows, g

    def test_all_arms_use_same_generator_and_null_is_not_a_fake_answer(self):
        rows, g = self.records()
        self.assertEqual([r["arm"] for r in rows], list(ARMS))
        self.assertEqual(len(g.calls), len(ARMS))
        self.assertTrue(any(not sources for _, sources in g.calls))
        self.assertTrue(
            all(r["answer"] == "independent generated text [E1]" for r in rows)
        )
        self.assertEqual(len({r["feature_digest"] for r in rows}), 1)
        self.assertEqual(len({r["pool_digest"] for r in rows}), 1)

    def test_source_byte_position_survives_selection(self):
        q, pool, f, _ = example()
        s = selected_window(q, pool, f, 1, set())[0]
        w = pool.windows[1]
        self.assertEqual(
            (s["source_start"], s["source_end"], s["excerpt"]), (w.start, w.end, w.text)
        )
        self.assertEqual(s["label"], "E1")
        with self.assertRaises(ValueError):
            selected_window(q, pool, replace(f, pool_digest="wrong"), 1, set())
        with self.assertRaises(ValueError):
            selected_window(q, pool, f, 1, {"root"})

    def test_learned_forced_is_not_frozen_forced(self):
        self.assertEqual(choose([2.0, 1.0, 3.0], ("a", "b"), allow_null=False), 0)
        self.assertEqual(choose([1.0, 2.0, 3.0], ("a", "b"), allow_null=False), 1)
        self.assertIsNone(choose([1.0, 2.0, 3.0], ("a", "b"), allow_null=True))
        with self.assertRaises(ValueError):
            choose([float("nan"), 0], ("a",), allow_null=False)

    def test_generator_pool_or_duplicate_drift_rejects(self):
        original, _ = self.records()
        for change in (
            lambda x: x.append(x[0]),
            lambda x: x[1].update(pool_digest="changed"),
            lambda x: x[1]["receipt"].update(generator_profile="different"),
            lambda x: x[1]["receipt"].update(generator_identity="different"),
        ):
            rows = deepcopy(original)
            change(rows)
            with self.assertRaises(ValueError):
                matched_report(rows, ["q"])

    def test_missing_answers_and_failed_calls_remain_in_uncertainty(self):
        rows, _ = self.records()
        rows[1].update(status="failed", error="test failure")
        report = matched_report(rows, ["q"])
        r = report["contrasts"]["test/forced"]
        self.assertEqual(r["missing_or_failed_pairs"], 1)
        self.assertEqual(r["answer_f1_family_delta_interval"], [-1.0, 1.0])
        self.assertFalse(report["superiority_claim"])

    def test_scoring_does_not_turn_references_into_answers(self):
        self.assertEqual(answer_scores("Wrong. [E1]", ("blue",), False)["f1"], 0)
        self.assertEqual(
            answer_scores("Blue. [E1]", ("blue",), False)["exact_match"], 1
        )
        self.assertEqual(
            answer_scores("anything", None, None), dict(exact_match=None, f1=None)
        )
        self.assertEqual(
            answer_scores("I do not have enough evidence.", (), True)["f1"], 1
        )
        self.assertEqual(answer_scores("An invented answer", (), True)["f1"], 0)


if __name__ == "__main__":
    unittest.main()
