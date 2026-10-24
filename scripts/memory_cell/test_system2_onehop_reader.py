"""Predeclared one-hop source controls, immutable answer receipts and fail-closed scores."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from system2_onehop_reader import (
    ARMS,
    READER_IDENTITY,
    READER_PROFILE,
    cases,
    evaluate_one,
    run,
    score,
    select,
)
from system2_multihop_evidence import parse_relation
from system2_multihop_trial import ABSTAIN


class _Bundle:
    def __init__(self, selected):
        self.selected = selected

    def seal(self):
        return "fixture-" + ",".join(d.identity for d in self.selected)


def _evidence(_case, selected, _arm):
    return _Bundle(selected), {}, "registered-frontier"


class FakeReader:
    def __init__(self, *, fail_at=None, no_evidence_hallucination=False):
        self.calls = 0
        self.fail_at = fail_at
        self.no_evidence_hallucination = no_evidence_hallucination

    def answer(self, question, bundle, _originals, *, frontier, revoked, token_limit):
        self.calls += 1
        if self.calls == self.fail_at:
            raise RuntimeError("injected Reader failure")
        assert frontier == "registered-frontier" and token_limit == 1024 and not revoked
        selected = bundle.selected
        target = question.content.split("device ", 1)[-1].rstrip("?")
        candidate = [
            (i, e[3])
            for i, doc in enumerate(selected)
            if (e := parse_relation(doc)) and e[0] == "device" and e[1] == target
        ]
        if candidate:
            label, token = candidate[0]
            answer = f"{token} [E{label + 1}]"
        elif self.no_evidence_hallucination:
            answer = "TOK-ABCD123 [E1]"
        else:
            answer = ABSTAIN
        receipt = dict(
            reader_identity=READER_IDENTITY,
            reader_profile=READER_PROFILE,
            bundle_digest=bundle.seal(),
            token_limit=token_limit,
            trainable_parameters=0,
            answer_postprocessed=False,
            generated_tokens=11,
        )
        return answer, receipt


class OneHopTests(unittest.TestCase):
    def test_unique_registered_cohort_and_disjoint_query_identity(self):
        registered = cases()
        self.assertEqual(len(registered), 20)
        self.assertEqual(len({c.question.identity for c in registered}), 20)
        self.assertEqual(len({c.original_question_id for c in registered}), 20)
        for c in registered:
            self.assertNotEqual(c.original_question_id, c.question.identity)
            self.assertEqual(
                len([d for d in c.documents if d.identity == c.required_id]), 1
            )

    def test_all_four_arms_preserve_correct_source_presence(self):
        for c in cases():
            for arm, expected_count, suff in (
                ("single_fact", 1, True),
                ("fact_plus_distractors", 3, True),
                ("distractors_only", 3, False),
                ("no_evidence", 0, False),
            ):
                chosen = select(c.question, c.documents, arm)
                self.assertEqual(len(chosen), expected_count)
                self.assertEqual(c.required_id in {x.identity for x in chosen}, suff)

    def test_selector_never_reads_gold_answer(self):
        c = cases()[0]
        forged = replace(c, answer="TOK-ABCD1239", required_id="source-not-present")
        for arm in ARMS:
            self.assertEqual(
                select(c.question, c.documents, arm),
                select(forged.question, forged.documents, arm),
            )

    def test_rejects_duplicate_cross_scope_future_evidence(self):
        c = cases()[1]
        bad = replace(c.documents[0], scope="unrelated")
        for items in (
            c.documents + (c.documents[0],),
            c.documents[:1] + (bad,) + c.documents[2:],
            c.documents[:1]
            + (replace(c.documents[1], observed_at="2099-01-01"),)
            + c.documents[2:],
        ):
            with self.assertRaises(ValueError):
                select(c.question, items, "single_fact")

    def test_strict_grounded_proof_requires_correct_citation(self):
        c = cases()[0]
        chosen = select(c.question, c.documents, "single_fact")
        ids = [d.identity for d in chosen]
        self.assertTrue(
            evaluate_one(c, "single_fact", ids, f"{c.answer} [E1]")[
                "grounded_answer_success"
            ]
        )
        for text in (
            c.answer,
            f"{c.answer} E1:",
            f"{c.answer} [E2]",
            f"{c.answer} [E1] TOK-ABCD123",
            "TOK-0000000 [E1]",
        ):
            self.assertFalse(
                evaluate_one(c, "single_fact", ids, text)["grounded_answer_success"]
            )

    def test_unsupported_copy_not_accepted(self):
        c = cases()[0]
        ids = [d.identity for d in select(c.question, c.documents, "distractors_only")]
        row = evaluate_one(c, "distractors_only", ids, c.answer + " [E1]")
        self.assertTrue(row["target_token_mentioned"])
        self.assertTrue(row["unsupported_answer"])
        self.assertFalse(row["grounded_answer_success"])
        self.assertFalse(row["conditional_task_success"])

    def test_correct_refusal_is_not_grounded_answer_yield(self):
        c = cases()[0]
        for arm in ("no_evidence", "distractors_only"):
            ids = [d.identity for d in select(c.question, c.documents, arm)]
            row = evaluate_one(c, arm, ids, ABSTAIN)
            self.assertTrue(row["conditional_task_success"])
            self.assertFalse(row["grounded_answer_success"])

    def test_invalid_citation_or_changed_source_refused(self):
        c = cases()[0]
        ids = [d.identity for d in select(c.question, c.documents, "single_fact")]
        with self.assertRaises(ValueError):
            evaluate_one(c, "single_fact", ids + ["forged"], c.answer + " [E1]")
        with self.assertRaises(ValueError):
            evaluate_one(c, "missing", ids, c.answer + " [E1]")

    def test_census_requires_every_question_arm_once(self):
        c = cases()
        rows = [
            dict(qid=x.question.identity, arm=arm, status="failed")
            for x in c
            for arm in ARMS
        ]
        _, summary = score(rows, c)
        self.assertEqual(len(summary), 4)
        self.assertTrue(
            all(
                x["failures"] == 20 and x["grounded_answer_success"] == 0
                for x in summary
            )
        )
        with self.assertRaises(ValueError):
            score(rows[:-1], c)
        with self.assertRaises(ValueError):
            score(rows + rows[:1], c)

    def test_mock_reader_generates_every_predeclared_position_and_seals(self):
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp) / "onehop"
            fake = FakeReader()
            with patch("system2_onehop_reader.evidence", side_effect=_evidence):
                results = run(dst, fake, source_commit="a" * 40)
            self.assertEqual(fake.calls, 80)
            self.assertEqual(
                [x["grounded_answer_success"] for x in results], [20, 20, 0, 0]
            )
            self.assertEqual([x["strict_abstentions"] for x in results], [0, 0, 20, 20])
            raw = (dst / "raw-answers.jsonl").read_bytes()
            seal = json.loads((dst / "raw-seal.json").read_text())
            self.assertEqual(seal["sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(seal["rows"], 80)
            self.assertEqual(
                json.loads((dst / "summary.json").read_text())["candidate_disposition"],
                "reader_singlehop_preflight_passed",
            )
            self.assertEqual(len((dst / "starts.jsonl").read_text().splitlines()), 80)

    def test_no_evidence_hallucination_keeps_true_denominator(self):
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp) / "bad"
            with patch("system2_onehop_reader.evidence", side_effect=_evidence):
                results = run(
                    dst,
                    FakeReader(no_evidence_hallucination=True),
                    source_commit="b" * 40,
                )
            self.assertEqual(results[3]["strict_abstentions"], 0)
            self.assertEqual(results[3]["unsupported_answers"], 20)
            self.assertEqual(
                json.loads((dst / "summary.json").read_text())["candidate_disposition"],
                "reader_singlehop_preflight_failed",
            )

    def test_failed_reader_call_retains_unknown_not_negative(self):
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp) / "failed"
            with patch("system2_onehop_reader.evidence", side_effect=_evidence):
                with self.assertRaises(RuntimeError):
                    run(dst, FakeReader(fail_at=2), source_commit="c" * 40)
            summary = json.loads((dst / "summary.json").read_text())
            self.assertEqual((summary["recorded"], summary["failed"]), (80, 1))
            rows = [
                json.loads(x)
                for x in (dst / "raw-answers.jsonl").read_text().splitlines()
            ]
            self.assertEqual(sum(x["status"] == "failed" for x in rows), 1)
            self.assertTrue((dst / "run-failure.json").exists())

    def test_invalid_source_sha_does_not_create_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp) / "never"
            with self.assertRaises(ValueError):
                run(dst, FakeReader(), source_commit="wrong")
            self.assertFalse(dst.exists())


if __name__ == "__main__":
    unittest.main()
