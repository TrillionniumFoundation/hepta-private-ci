"""Hermetic counterfactual tests; native frozen Reader results remain external."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from system2_multihop_counterfactual import (
    ARMS,
    PAIRS,
    START_INDEX,
    cases,
    select,
    source_manifest,
)
from system2_multihop_evidence import join_path, make_case, parse_relation, text_terms
from system2_multihop_counterfactual_trial import ABSTAIN, evaluate, run, score


def fake_evidence(case, selected, arm):
    return (
        SimpleNamespace(seal=lambda: "test-bundle-" + arm),
        {d.identity: d for d in case.documents},
        "fixture-frontier",
    )


class SyntheticReader:
    def answer(self, question, bundle, originals, *, frontier, revoked, token_limit):
        # The unit-test Reader is an explicitly synthetic conditional simulator:
        # it never receives gold targets or reads the generator's answer field.
        # It must not be reported as a pretrained model result.
        self.calls += 1
        selected = tuple(originals[k] for k in self.sources[self.calls - 1])
        path = join_path(question, selected)
        if not path:
            return ABSTAIN, {
                "input_tokens": 33,
                "generated_tokens": 10,
                "fixture": True,
            }
        last = parse_relation(path[-1])
        labels = [f"[E{selected.index(d) + 1}]" for d in path]
        return last[3] + " " + " ".join(labels), {
            "input_tokens": 40,
            "generated_tokens": 20,
            "fixture": True,
        }

    def __init__(self, sources):
        self.sources = sources
        self.calls = 0


class CounterfactualTests(unittest.TestCase):
    def test_32_new_fixed_questions_disjoint_from_prior_twenty(self):
        self.assertEqual(PAIRS, 16)
        self.assertGreaterEqual(START_INDEX, 20)
        ps = cases()
        self.assertEqual(len(ps), PAIRS)
        self.assertEqual(len({c.question.identity for ab in ps for c in ab}), 32)
        self.assertFalse(
            set(c.question.identity for ab in ps for c in ab)
            & set(make_case(i).question.identity for i in range(20))
        )

    def test_pair_changes_answer_not_query_or_bag_of_words(self):
        for first, second in cases():
            self.assertNotEqual(first.answer, second.answer)
            self.assertEqual(first.question.content, second.question.content)
            self.assertEqual(first.question.observed_at, second.question.observed_at)
            self.assertEqual(first.hops, second.hops)
            self.assertEqual(
                Counter(t for d in first.documents for t in text_terms(d.content)),
                Counter(t for d in second.documents for t in text_terms(d.content)),
            )
            self.assertEqual(
                [len(d.content.encode()) for d in first.documents],
                [len(d.content.encode()) for d in second.documents],
            )
            self.assertNotEqual(source_manifest(first), source_manifest(second))

    def test_all_selected_paths_have_fixed_cardinality_and_no_leakage(self):
        for group in cases():
            for c in group:
                for arm in ARMS:
                    selected = select(arm, c.question, c.documents)
                    self.assertEqual(len(selected), 3)
                    self.assertEqual(len(set(d.identity for d in selected)), 3)
                    complete = bool(join_path(c.question, selected))
                    if arm in ("joined_top3", "reversed_join_top3"):
                        self.assertTrue(complete)
                    if arm in ("missing_start_top3", "terminal_only_top3"):
                        self.assertFalse(complete)
                        # Correct target token is present but *not* justified by
                        # a complete typed chain from the question's project.
                        self.assertTrue(any(c.answer in d.content for d in selected))

    def test_reverse_keeps_exact_set_but_changes_reader_order(self):
        for group in cases():
            for c in group:
                a = select("joined_top3", c.question, c.documents)
                b = select("reversed_join_top3", c.question, c.documents)
                self.assertEqual({d.identity for d in a}, {d.identity for d in b})
                self.assertEqual(a, tuple(reversed(b)))

    def test_selection_does_not_receive_gold_answer_field(self):
        for c in cases()[0]:
            alternate = replace(c, answer="TOK-FAKE99", required_ids=())
            for arm in ARMS:
                self.assertEqual(
                    select(arm, c.question, c.documents),
                    select(arm, alternate.question, alternate.documents),
                )

    def test_wrong_or_unsupported_target_is_not_strict_success(self):
        c = cases()[0][0]
        selected = select("joined_top3", c.question, c.documents)
        labels = " ".join(
            "[E" + str(selected.index(d) + 1) + "]"
            for d in join_path(c.question, selected)
        )
        r = score(c, selected, c.answer + " " + labels)
        self.assertTrue(r["strict_success"])
        self.assertTrue(r["cites_required"])
        self.assertFalse(score(c, selected, c.answer)["strict_success"])
        self.assertFalse(score(c, selected, "TOK-FAKE99 " + labels)["strict_success"])
        bad = select("terminal_only_top3", c.question, c.documents)
        self.assertFalse(score(c, bad, c.answer + " [E1]")["strict_success"])
        self.assertTrue(score(c, bad, c.answer + " [E1]")["copied_target_without_path"])
        self.assertTrue(score(c, bad, ABSTAIN)["strict_success"])

    def test_invalid_scope_and_future_sources_fail_closed(self):
        c = cases()[0][0]
        d = c.documents[0]
        for replacement in (
            replace(d, scope="wrong"),
            replace(d, observed_at="2099-01-01T00:00:00+00:00"),
        ):
            docs = (replacement,) + c.documents[1:]
            with self.assertRaises(ValueError):
                select("joined_top3", c.question, docs)
        with self.assertRaises(ValueError):
            select("unregistered", c.question, c.documents)

    def test_complete_answer_evaluation_keeps_pair_denominators(self):
        pairs = cases()[:2]
        rows = []
        for j, group in enumerate(pairs):
            for v, c in enumerate(group):
                for arm in ARMS:
                    selected = select(arm, c.question, c.documents)
                    path = join_path(c.question, selected)
                    raw = (
                        c.answer
                        + " "
                        + " ".join(f"[E{selected.index(d) + 1}]" for d in path)
                        if path
                        else ABSTAIN
                    )
                    rows.append(
                        dict(
                            qid=c.question.identity,
                            arm=arm,
                            status="succeeded",
                            selected=[d.identity for d in selected],
                            answer=raw,
                        )
                    )
        scores, summary = evaluate(rows, pairs)
        self.assertEqual(len(scores), 20)
        by = {x["arm"]: x for x in summary}
        self.assertEqual(
            by["joined_top3"]["both_counterfactual_variants_exact_and_cited"], 2
        )
        self.assertEqual(
            by["reversed_join_top3"]["both_counterfactual_variants_exact_and_cited"], 2
        )
        self.assertEqual(by["missing_start_top3"]["strict_successes"], 4)
        self.assertEqual(by["terminal_only_top3"]["strict_successes"], 4)
        self.assertEqual(by["missing_start_top3"]["complete_evidence"], 0)
        with self.assertRaises(ValueError):
            evaluate(rows[:-1], pairs)
        with self.assertRaises(ValueError):
            evaluate(rows + rows[:1], pairs)

    def test_real_runner_seals_before_scoring_and_does_not_train(self):
        ps = cases()[:2]
        entries = [
            (j, v, c, arm)
            for j, g in enumerate(ps)
            for v, c in enumerate(g)
            for arm in ARMS
        ]
        entries.sort(
            key=lambda x: (
                x[0],
                (
                    x[1] * len(ARMS)
                    + ARMS.index(x[3])
                    + int(
                        __import__("system2_multihop_evidence").digest(
                            x[2].question.content
                        )[:8],
                        16,
                    )
                )
                % (2 * len(ARMS)),
            )
        )
        expected = [
            tuple(d.identity for d in select(arm, c.question, c.documents))
            for _, _, c, arm in entries
        ]
        reader = SyntheticReader(expected)
        with tempfile.TemporaryDirectory() as root:
            out = Path(root) / "run"
            original_score = score

            def check_seal(*args):
                self.assertTrue((out / "raw-seal.json").exists())
                return original_score(*args)

            with (
                patch("system2_multihop_counterfactual_trial.cases", return_value=ps),
                patch(
                    "system2_multihop_counterfactual_trial.evidence",
                    side_effect=fake_evidence,
                ),
                patch(
                    "system2_multihop_counterfactual_trial.score",
                    side_effect=check_seal,
                ),
            ):
                report = run(out, reader, source_commit="a" * 40, num_pairs=2)
            self.assertEqual(
                (
                    report["census"]["planned"],
                    report["census"]["recorded"],
                    report["census"]["failed"],
                ),
                (20, 20, 0),
            )
            self.assertEqual(reader.calls, 20)
            self.assertTrue((out / "raw-seal.json").exists())
            self.assertEqual(
                len((out / "raw-answers.jsonl").read_text().splitlines()), 20
            )
            self.assertEqual(report["arms"][0]["pair_denominator"], 2)

    def test_reader_errors_keep_full_attempt_census(self):
        ps = cases()[:1]

        class Broken:
            calls = 0

            def answer(self, *args, **kwargs):
                self.calls += 1
                raise RuntimeError("test Reader unavailable")

        reader = Broken()
        with tempfile.TemporaryDirectory() as root:
            out = Path(root) / "run"
            with (
                patch("system2_multihop_counterfactual_trial.cases", return_value=ps),
                patch(
                    "system2_multihop_counterfactual_trial.evidence",
                    side_effect=fake_evidence,
                ),
            ):
                with self.assertRaises(RuntimeError):
                    run(out, reader, source_commit="b" * 40, num_pairs=1)
            self.assertEqual(reader.calls, 10)
            self.assertEqual(
                len((out / "raw-answers.jsonl").read_text().splitlines()), 10
            )
            self.assertEqual(
                json.loads((out / "summary.json").read_text())["census"]["failed"], 10
            )
            self.assertTrue((out / "run-failure.json").exists())

    def test_actual_native_bundle_is_valid_when_full_repo_available(self):
        try:
            import native  # noqa: F401
            import evidence_bundle  # noqa: F401
        except ImportError:
            self.skipTest(
                "repository native evidence owner not present in source-only tests"
            )
        from system2_multihop_trial import evidence

        c = cases()[0][0]
        selected = select("joined_top3", c.question, c.documents)
        bundle, originals, frontier = evidence(c, selected, "joined_top3")
        bundle.validate(c.question, originals, frontier=frontier, revoked=set())
        self.assertEqual(len(bundle.selected), 3)


if __name__ == "__main__":
    unittest.main()
