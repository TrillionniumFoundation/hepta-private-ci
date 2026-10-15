"""Real synthetic document/query protocols, with fake Reader only for mechanics."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from system2_multihop_evidence import (
    ARMS,
    TOP_K,
    choose,
    fixed_cases,
    join_path,
    make_case,
    parse_relation,
    validate_case,
)
from system2_multihop_trial import ABSTAIN, census, run, score


class FixedReader:
    def __init__(self, fail_at=None):
        self.calls = []
        self.fail_at = fail_at

    def answer(self, query, bundle, originals, *, frontier, revoked, token_limit):
        self.calls.append(
            (query.identity, bundle.label, tuple(d.identity for d in bundle.selected))
        )
        assert token_limit == 1024 and not revoked and frontier
        if len(self.calls) == self.fail_at:
            raise RuntimeError("injected Reader failure")
        return ABSTAIN, {
            "input_tokens": 50,
            "generated_tokens": 6,
            "reader_identity": "fixture-only",
        }


class FakeBundle:
    def __init__(self, selected, arm):
        self.selected = selected
        self.label = arm

    def seal(self):
        return "test-only-bundle-seal"


def fake_evidence(case, selected, arm):
    return (
        FakeBundle(selected, arm),
        {d.identity: d for d in case.documents},
        "test-frontier",
    )


class SyntheticEvidenceTests(unittest.TestCase):
    def test_20_unique_bound_cases_and_minimal_paths(self):
        cases = fixed_cases()
        self.assertEqual(len(cases), 20)
        self.assertEqual(len({c.question.identity for c in cases}), 20)
        self.assertEqual(sum(c.hops == 2 for c in cases), 10)
        self.assertEqual(sum(c.hops == 3 for c in cases), 10)
        self.assertEqual(sum(c.attack_distractor for c in cases), 5)
        for c in cases:
            validate_case(c)
            self.assertEqual(
                tuple(d.identity for d in join_path(c.question, c.documents)),
                c.required_ids,
            )
            for doc_id in c.required_ids:
                self.assertFalse(
                    join_path(
                        c.question,
                        tuple(d for d in c.documents if d.identity != doc_id),
                    )
                )

    def test_every_arm_bounded_and_programmatically_sufficient_only_on_join(self):
        cases = fixed_cases()
        stats = {arm: 0 for arm in ARMS}
        for c in cases:
            for arm in ARMS:
                docs = choose(arm, c.question, c.documents)
                self.assertEqual(len(docs), 0 if arm == "no_evidence" else TOP_K)
                self.assertEqual(len({d.identity for d in docs}), len(docs))
                stats[arm] += set(c.required_ids).issubset({d.identity for d in docs})
        self.assertEqual(stats["joined_top3"], 20)
        self.assertEqual(stats["premise_removed"], 0)
        self.assertEqual(stats["no_evidence"], 0)
        self.assertLess(stats["bm25_top3"], stats["joined_top3"])
        self.assertLess(stats["lexical_top3"], stats["joined_top3"])

    def test_answer_labels_never_affect_selection(self):
        for c in fixed_cases():
            altered = replace(c, answer="TOK-AAAAAAA", required_ids=("fake",))
            for arm in ARMS:
                before = choose(arm, c.question, c.documents)
                after = choose(arm, altered.question, altered.documents)
                self.assertEqual(before, after)

    def test_invalid_source_identity_time_and_scope_fail_closed(self):
        c = make_case(3)
        docs = list(c.documents)
        docs.append(docs[0])
        with self.assertRaises(ValueError):
            choose("joined_top3", c.question, tuple(docs))
        docs = list(c.documents)
        docs[0] = replace(docs[0], scope="wrong-scope")
        with self.assertRaises(ValueError):
            choose("bm25_top3", c.question, tuple(docs))
        with self.assertRaises(ValueError):
            choose(
                "joined_top3",
                replace(c.question, content="unknown intent"),
                c.documents,
            )
        docs = list(c.documents)
        docs[0] = replace(docs[0], observed_at="2030-01-01T00:00:00+00:00")
        with self.assertRaises(ValueError):
            choose("bm25_top3", c.question, tuple(docs))

    def test_injection_is_not_interpreted_as_a_relation(self):
        for c in fixed_cases():
            attack = [
                d
                for d in c.documents
                if "Ignore all previous instructions" in d.content
            ]
            if c.attack_distractor:
                self.assertEqual(len(attack), 1)
                self.assertIsNone(parse_relation(attack[0]))
                self.assertNotIn(attack[0].identity, c.required_ids)
            else:
                self.assertEqual(len(attack), 0)

    def test_exact_synthetic_answer_and_bound_citations(self):
        c = make_case(1)
        selected = choose("joined_top3", c.question, c.documents)
        correct = "The clearance token is " + c.answer + " [E1] [E2] [E3]."
        row = score(c, "joined_top3", [d.identity for d in selected], correct)
        self.assertTrue(row["strict_task_success"])
        self.assertTrue(row["cites_all_required_sources"])
        self.assertFalse(
            score(
                c, "joined_top3", [d.identity for d in selected], c.answer + " [E99]"
            )["strict_task_success"]
        )
        self.assertFalse(
            score(c, "joined_top3", [d.identity for d in selected], c.answer + " [E1]")[
                "strict_task_success"
            ]
        )
        negative = choose("premise_removed", c.question, c.documents)
        self.assertTrue(
            score(c, "premise_removed", [d.identity for d in negative], ABSTAIN)[
                "strict_task_success"
            ]
        )
        self.assertFalse(
            score(c, "premise_removed", [d.identity for d in negative], correct)[
                "strict_task_success"
            ]
        )

    def test_missing_or_duplicate_planned_rows_rejected(self):
        qids = [c.question.identity for c in fixed_cases(2)]
        rows = [dict(qid=q, arm=a, status="failed") for q in qids for a in ARMS]
        self.assertEqual(census(rows, qids)["planned"], 10)
        for bad in (
            rows[:-1],
            rows + rows[:1],
            rows + [dict(qid="unknown", arm=ARMS[0], status="failed")],
        ):
            with self.assertRaises(ValueError):
                census(bad, qids)

    def test_full_runner_real_pools_fake_reader_and_raw_seal(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("system2_multihop_trial.evidence", fake_evidence),
        ):
            reader = FixedReader()
            out = Path(tmp) / "run"
            receipt = run(out, reader, source_commit="a" * 40, count=4)
            self.assertEqual(
                receipt["census"],
                {"planned": 20, "recorded": 20, "succeeded": 20, "failed": 0},
            )
            self.assertEqual(len(reader.calls), 20)
            raw = (out / "raw-answers.jsonl").read_bytes()
            seal = json.loads((out / "raw-seal.json").read_text())
            self.assertEqual(seal["sha256"], hashlib.sha256(raw).hexdigest())
            self.assertFalse(seal["scoring_started"])
            self.assertEqual(len(json.loads((out / "scored.json").read_text())), 20)

    def test_reader_failure_retained_with_complete_denominator(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("system2_multihop_trial.evidence", fake_evidence),
        ):
            out = Path(tmp) / "failed"
            with self.assertRaises(RuntimeError):
                run(out, FixedReader(fail_at=2), source_commit="b" * 40, count=2)
            summary = json.loads((out / "summary.json").read_text())
            self.assertEqual(
                summary["census"],
                {"planned": 10, "recorded": 10, "succeeded": 9, "failed": 1},
            )
            self.assertEqual(
                len((out / "raw-answers.jsonl").read_text().splitlines()), 10
            )
            self.assertTrue((out / "run-failure.json").exists())

    def test_repo_native_bundle_contract_when_available(self):
        import importlib.util

        if importlib.util.find_spec("evidence_bundle") is None:
            self.skipTest(
                "actual repository module unavailable in standalone source slice"
            )
        from system2_multihop_trial import evidence

        c = make_case(1)
        selected = choose("joined_top3", c.question, c.documents)
        bundle, originals, frontier = evidence(c, selected, "joined_top3")
        bundle.validate(c.question, originals, frontier=frontier, revoked=set())
        corrupted = dict(originals)
        corrupted[selected[0].identity] = replace(
            selected[0], content="tampered source"
        )
        with self.assertRaises(ValueError):
            bundle.validate(c.question, corrupted, frontier=frontier, revoked=set())

    def test_bad_run_commit_rejected_pre_io(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "run"
            with self.assertRaises(ValueError):
                run(out, FixedReader(), source_commit="fake", count=3)
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
