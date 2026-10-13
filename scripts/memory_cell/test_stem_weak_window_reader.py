"""Synthetic label-assisted Reader diagnostic; no real model results claimed."""

from dataclasses import asdict
from types import SimpleNamespace as Obj
import unittest

from native import Question, Target, digest
from stem_weak_window_reader import (
    prepare_native_window_interventions,
    generate_native_window_interventions,
    review_native_window_interventions,
)


PHASES = ("test", "transfer")
READER = "same-pinned-weights"
PROFILE = "same-frozen-prompt"


class Window:
    def __init__(self, qid, name, position):
        self.source_id = name + "-" + qid
        self.scope = "scope-" + qid
        self.observed_at = "2023-04-10"
        self.root = "root-" + qid
        self.name = name
        self.position = position

    def identity(self):
        return digest((self.scope, self.name, self.position))


class Pool:
    def __init__(self, qid):
        self.windows = (
            Window(qid, "base", 0),
            Window(qid, "support", 1),
        )

    def seal(self):
        return digest(tuple(w.identity() for w in self.windows))


def make():
    queries, pools, features, targets, frozen = {}, {}, {}, {}, []
    for phase in PHASES:
        queries[phase] = []
        for i in range(8):
            qid = f"{phase}-{i}"
            q = Question(qid, qid, "scope-" + qid, "Where was the object?", "2024-01-01")
            queries[phase].append(q)
            pool = Pool(qid)
            pools[qid] = pool
            features[qid] = Obj(
                question_id=qid,
                candidate_ids=tuple(w.identity() for w in pool.windows),
                pool_digest=pool.seal(),
                frozen_scores=Obj(tolist=lambda: [6.0, 3.0]),
            )
            if (phase, i) in (("test", 6), ("test", 7), ("transfer", 7)):
                targets[qid] = Target(None, "fixture", (), True)
            elif (phase, i) in (("test", 1), ("test", 2)):
                targets[qid] = Target("right", "fixture", ("missing-" + qid,), False)
            elif (phase, i) in (("test", 0), ("transfer", 0)):
                targets[qid] = Target(
                    "right", "fixture", ("support-" + qid,), False
                )
            else:
                targets[qid] = Target(
                    "right", "fixture", ("base-" + qid,), False
                )
            frozen.append(dict(
                stage=48, phase=phase, arm="frozen_rerank",
                question_id=qid, status="succeeded", selected=0,
                pool_digest=pool.seal(), answer="wrong",
                receipt=dict(
                    generator_identity=READER, generator_profile=PROFILE,
                    observable_query=asdict(q),
                ),
            ))
    return queries, pools, features, targets, frozen


def select_window(q, pool, feature, position, revoked):
    assert revoked == set()
    assert feature.pool_digest == pool.seal()
    w = pool.windows[position]
    return (dict(
        label="E1", scope=q.scope, root=w.root,
        observed_at=w.observed_at, excerpt="source text " + w.name,
        original_id=w.source_id, id=w.identity(),
    ),)


def fake_reader(q, evidence, key):
    if not key.startswith("native-weak-window/") or len(evidence) != 1:
        raise AssertionError("unexpected selected Reader condition")
    body = asdict(q)
    return "right", dict(
        generator_identity=READER, generator_profile=PROFILE,
        observable_query=body, delivered_evidence=list(evidence),
        canonical_request_digest=digest((READER, PROFILE, body, evidence)),
        actual_reader_execution=True,
    )


class WeakWindowReaderTests(unittest.TestCase):
    def prepared(self):
        q, pools, features, targets, frozen = make()
        return (
            q, targets, prepare_native_window_interventions(
                q, frozen, pools, features, targets,
                selected_window=select_window,
            ),
        )

    def test_only_two_weakly_missed_sources_generate_reader_calls(self):
        questions, targets, prepared = self.prepared()
        counts = {}
        for p in prepared:
            counts[p["disposition"]] = counts.get(p["disposition"], 0) + 1
        self.assertEqual(counts, dict(
            eligible_native_support_top1_miss=2,
            native_support_not_retrieved=2,
            native_support_already_selected=9,
            native_unanswerable=3,
        ))
        calls = []
        def generator(q, evidence, key):
            calls.append(q.identity)
            return fake_reader(q, evidence, key)
        records = generate_native_window_interventions(
            prepared, questions, generator,
        )
        self.assertEqual(calls, ["test-0", "transfer-0"])
        self.assertEqual(len(records), 16)
        self.assertEqual(sum(x["status"] == "succeeded" for x in records), 2)
        self.assertFalse(any("diagnostic_evidence" in x for x in records))
        report = review_native_window_interventions(
            records, targets, lambda answer, t: 1.0 if answer == t.answer else 0.0,
        )
        self.assertEqual(report["eligible_postpolicy_labelled_source_substitutions"], 2)
        self.assertEqual(report["paired_answers_scored"], 2)
        self.assertEqual(report["conditional_paired_reader_f1_delta"], 1)
        self.assertFalse(report["independent_sufficient_evidence_oracle"])
        self.assertFalse(report["production_accepted"])

    def test_failed_reader_does_not_shrink_denominator(self):
        q, targets, plan = self.prepared()
        def bad_reader(query, evidence, record_key):
            if query.identity == "test-0":
                raise RuntimeError("real Reader refused")
            return fake_reader(query, evidence, record_key)
        rows = generate_native_window_interventions(plan, q, bad_reader)
        report = review_native_window_interventions(
            rows, targets, lambda answer, target: float(answer == target.answer),
        )
        self.assertEqual(report["original_test_transfer_questions"], 16)
        self.assertEqual(report["actual_reader_successes"], 1)
        self.assertEqual(report["actual_reader_failures"], 1)
        self.assertEqual(report["paired_answers_scored"], 1)
        self.assertEqual(report["all_eligible_score_bounds"], [0, 1])

    def test_changed_reader_or_request_receipt_is_never_counted_as_success(self):
        q, _, plan = self.prepared()
        for field in ("generator_identity", "generator_profile",
                      "canonical_request_digest", "delivered_evidence",
                      "actual_reader_execution"):
            def tamper(query, evidence, key):
                answer, receipt = fake_reader(query, evidence, key)
                receipt[field] = (
                    False if field == "actual_reader_execution" else
                    [] if field == "delivered_evidence" else "mismatched"
                )
                return answer, receipt
            with self.subTest(field=field):
                rows = generate_native_window_interventions(plan, q, tamper)
                self.assertEqual(sum(x["status"] == "failed" for x in rows), 2)

    def test_original_pool_and_time_are_bound(self):
        for mode in ("pool", "feature", "future", "scope"):
            q, pools, features, targets, frozen = make()
            if mode == "pool":
                features["test-0"].pool_digest = "another"
            elif mode == "feature":
                features["test-0"].candidate_ids = ("forged",)
            elif mode == "future":
                pools["test-0"].windows[1].observed_at = "2025-01-01"
            else:
                pools["test-0"].windows[1].scope = "other-scope"
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                prepare_native_window_interventions(
                    q, frozen, pools, features, targets,
                    selected_window=select_window,
                )

    def test_no_gold_answer_text_enters_label_guided_reader_prompt(self):
        q, _, plan = self.prepared()
        calls = []
        def inspect(question, evidence, key):
            calls.append((question.content, evidence[0]["excerpt"]))
            assert "right" not in question.content
            assert all("right" not in x["excerpt"] for x in evidence)
            return fake_reader(question, evidence, key)
        generate_native_window_interventions(plan, q, inspect)
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(p["gold_answer_passed_to_reader"] is False
                            for p in plan))

    def test_missing_or_duplicated_case_is_a_hard_error(self):
        q, targets, plan = self.prepared()
        for wrong in (plan[:-1], plan[:-1] + [dict(plan[0])]):
            with self.subTest(size=len(wrong)), self.assertRaises(ValueError):
                generate_native_window_interventions(wrong, q, fake_reader)
        result = generate_native_window_interventions(plan, q, fake_reader)
        with self.assertRaises(ValueError):
            review_native_window_interventions(result[:-1], targets, lambda a,t: 0.5)

    def test_frozen_baseline_failure_is_unavailable_not_a_valid_new_gain(self):
        q, pools, features, targets, original = make()
        row = next(x for x in original if x["question_id"] == "test-0")
        row.update(status="failed")
        row.pop("receipt")
        row.pop("answer")
        prepared = prepare_native_window_interventions(
            q, original, pools, features, targets, selected_window=select_window,
        )
        self.assertEqual(prepared[0]["disposition"], "frozen_reader_failed")
        rows = generate_native_window_interventions(prepared, q, fake_reader)
        self.assertEqual(sum(r["status"] == "succeeded" for r in rows), 1)

    def test_unresolved_support_is_not_promoted_to_gold_sufficiency(self):
        q, pools, features, targets, original = make()
        targets["test-0"] = Target("right", "fixture",
                                   ("support-test-0",), False, ("missing",))
        prepared = prepare_native_window_interventions(
            q, original, pools, features, targets, selected_window=select_window,
        )
        self.assertEqual(prepared[0]["disposition"], "native_support_unresolved")
        result = generate_native_window_interventions(prepared, q, fake_reader)
        self.assertEqual(sum(x["status"] == "succeeded" for x in result), 1)


if __name__ == "__main__":
    unittest.main()
