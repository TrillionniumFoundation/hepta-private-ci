"""Fixed new-question protocol and real coordinator tests using fixture ports."""

from dataclasses import replace
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from native import digest
from selector_head import TrainingCut
from system2_frozen_cohort import ARMS, Ports, execute, plan_cohort, summarize_answers
from test_system2_fewshot_cells import cohort


def questions():
    return [
        SimpleNamespace(
            identity=f"{fam}/q{i}",
            family=fam,
            scope=fam,
            content=f"What object does person {fam} number {i} hold?",
            observed_at="same-native-time",
        )
        for fam in ("a", "b")
        for i in range(15)
    ]


class FixedCohortTests(unittest.TestCase):
    def setUp(self):
        self.qs = questions()
        self.old = {
            "question_ids": {"train": ["a/q0", "b/q0"], "test": ["a/q1", "b/q1"]}
        }

    def test_all_old_ids_excluded_and_support_query_disjoint(self):
        p = plan_cohort(self.qs, self.old)
        self.assertEqual(p["planned_supports"], 4)
        self.assertEqual(p["planned_queries"], 16)
        self.assertEqual(p["planned_answers"], 128)
        for g in p["groups"]:
            self.assertFalse(set(g["support_ids"]) & set(g["query_ids"]))
            self.assertFalse(
                set(g["support_ids"] + g["query_ids"]) & set(p["excluded_question_ids"])
            )

    def test_plan_independent_of_input_order_and_target_metadata(self):
        before = plan_cohort(self.qs, self.old)
        for q in self.qs:
            q.target = object()  # This field is never inspected by planning.
        self.assertEqual(before, plan_cohort(list(reversed(self.qs)), self.old))

    def test_same_text_new_identity_does_not_count_as_new_question(self):
        self.qs[3].content = self.qs[0].content.upper()
        p = plan_cohort(self.qs, self.old)
        chosen = {q for g in p["groups"] for q in g["support_ids"] + g["query_ids"]}
        self.assertNotIn(self.qs[3].identity, chosen)

    def test_missing_family_capacity_and_duplicates_reject(self):
        for qs in (self.qs[:8], self.qs + [self.qs[0]]):
            with self.assertRaises((ValueError, KeyError)):
                plan_cohort(qs, self.old)

    def test_native_unicode_question_binding(self):
        self.qs[2].content = "What is José’s café?"
        p = plan_cohort(self.qs, self.old)
        for g in p["groups"]:
            for qid, binding in g["question_bindings"].items():
                q = next(q for q in self.qs if q.identity == qid)
                self.assertEqual(binding, digest((q.content, q.observed_at, q.scope)))

    def fixture_run(
        self,
        tmp,
        *,
        answer_failure=False,
        encode_failure=False,
        support_failure=False,
        unknown=False,
    ):
        rows, original = cohort()
        family = rows[0].features.family
        support_rows = tuple(
            replace(r, features=replace(r.features, question_id=f"support-{i}"))
            for i, r in enumerate(rows[:2])
        )
        fs = {
            f"query-{i}": replace(rows[0].features, question_id=f"query-{i}")
            for i in range(2)
        }
        group = dict(
            family=family,
            support_ids=[r.features.question_id for r in support_rows],
            query_ids=list(fs),
        )
        plan = dict(groups=[group], source_commit="a" * 40)
        out = Path(tmp) / "trial"
        events = []

        def support(g):
            events.append("support")
            self.assertFalse((out / "snapshot-freeze.json").exists())
            if support_failure:
                raise ValueError("support encoder failed")
            cut = TrainingCut(
                frozenset(g["support_ids"]),
                frozenset({family}),
                frozenset({family}),
                original.forbidden_roots,
                "fixture-cut",
            )
            return support_rows, cut, {"fixture": True}

        def encode(qid):
            self.assertTrue((out / "snapshot-freeze.json").is_file())
            events.append("encode")
            if encode_failure:
                raise ValueError("query encoder failed")
            return fs[qid]

        def answer(qid, selected):
            events.append("answer")
            self.assertTrue((out / "snapshot-freeze.json").is_file())
            self.assertFalse((out / "answer-seal.json").exists())
            if answer_failure:
                raise RuntimeError("Reader fixture failure")
            return "fixture answer", {"fixture": True, "qid": qid, "selected": selected}

        def score(row):
            self.assertTrue((out / "answer-seal.json").is_file())
            self.assertEqual(len((out / "answers.jsonl").read_text().splitlines()), 16)
            events.append("score")
            return dict(diagnostic_f1=None if unknown else 0.25, weak_source_hit=False)

        report = execute(
            plan, rows, original, Ports(support, encode, answer, score), out
        )
        return report, events, out

    def test_coordinator_freezes_before_query_encode_and_scores_after_answers(self):
        with tempfile.TemporaryDirectory() as tmp:
            report, events, _ = self.fixture_run(tmp)
            self.assertEqual(report["recorded"], 16)
            self.assertEqual(report["failed"], 0)
            self.assertEqual(events.count("support"), 1)
            self.assertEqual(events.count("answer"), 16)
            self.assertGreater(
                events.index("score"),
                max(i for i, e in enumerate(events) if e == "answer"),
            )

    def test_real_reader_failure_kept_in_full_census(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                self.fixture_run(tmp, answer_failure=True)
            r = json.loads((Path(tmp) / "trial/summary.json").read_text())
            self.assertEqual(r["failed"], 16)
            self.assertEqual(r["recorded"], 16)
            self.assertTrue(
                all(
                    x["all_planned_f1_bounds"] == [0.0, 1.0]
                    for x in r["by_arm"].values()
                )
            )

    def test_query_encoding_failure_does_not_remove_no_evidence_control(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                self.fixture_run(tmp, encode_failure=True)
            r = json.loads((Path(tmp) / "trial/summary.json").read_text())
            self.assertEqual(r["recorded"], 16)
            self.assertEqual(r["by_arm"]["no_evidence"]["reader_calls"], 2)
            self.assertEqual(r["by_arm"]["no_evidence"]["failed"], 0)
            self.assertEqual(r["failed"], 14)

    def test_support_failure_does_not_poison_frozen_or_shared(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                self.fixture_run(tmp, support_failure=True)
            r = json.loads((Path(tmp) / "trial/summary.json").read_text())
            for arm in ("frozen", "shared", "no_evidence", "ranked3"):
                self.assertEqual(r["by_arm"][arm]["failed"], 0)
            self.assertEqual(r["by_arm"]["differentiated"]["failed"], 2)

    def test_unscored_success_is_unknown_not_perfect(self):
        with tempfile.TemporaryDirectory() as tmp:
            r, _, _ = self.fixture_run(tmp, unknown=True)
            self.assertTrue(
                all(
                    x["all_planned_f1_bounds"] == [0.0, 1.0]
                    for x in r["by_arm"].values()
                )
            )
            self.assertEqual(
                r["candidate_disposition"], "stop_no_controlled_end_to_end_gain"
            )

    def test_state_mutation_aborts_before_scoring(self):
        from system2_frozen_cohort import predict as real

        def mutation(f, prior, delta, *args, **kwargs):
            result = real(f, prior, delta, *args, **kwargs)
            delta.add_(1)
            return result

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("system2_frozen_cohort.predict", side_effect=mutation),
        ):
            with self.assertRaisesRegex(ValueError, "mutated"):
                self.fixture_run(tmp)
            self.assertFalse((Path(tmp) / "trial/answer-seal.json").exists())

    def test_missing_duplicate_or_nonfinite_scores_reject(self):
        records = [
            dict(
                query_id="q",
                family="a",
                arm=a,
                status="succeeded",
                reader_attempted=True,
                seconds=0.1,
                diagnostic_f1=0.2,
            )
            for a in ARMS
        ]
        plan = {"groups": [{"family": "a", "query_ids": ["q"]}]}
        for rr in (
            records[:-1],
            records + records[:1],
            [dict(r, diagnostic_f1=True) for r in records],
        ):
            with self.assertRaises(ValueError):
                summarize_answers(rr, plan)


if __name__ == "__main__":
    unittest.main()
