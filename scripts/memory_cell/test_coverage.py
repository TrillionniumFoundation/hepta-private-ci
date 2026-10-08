import copy
import unittest

from benchmark_coverage import ARMS, decode_plan, aggregate, partition, plan_coverage
from native import Benchmark, Question


def benchmark(name="locomo"):
    questions = tuple(Question(f"q{i}-{j}", f"f{i}", f"s{i}", "question", "2024") for i in range(10) for j in range(3))
    return Benchmark(name, "a" * 64, (), questions, {}, {f"f{i}": f"f{i}" for i in range(10)})


def receipts(plan):
    return [{
        "fold": f, "shard": s, "coverage_digest": plan.seal(), "execution_binding": {"code": "pinned"}, "retained_bytes": 100,
        "results": {arm: [{"question_id": qid, "status": "succeeded", "hypothesis": "answer", "diagnostic_token_f1": 0.5}
                          for qid in plan.assigned(f, s)] for arm in ARMS},
    } for f in range(plan.folds) for s in range(plan.shards)]


class CoverageTests(unittest.TestCase):
    def test_all_native_questions_are_held_out_exactly_once_across_folds(self):
        b = benchmark()
        plan = plan_coverage(b, folds=5, shards=3, per_fold_limit=None)
        self.assertEqual({c[0] for c in plan.cases}, {q.identity for q in b.questions})
        self.assertEqual(len(plan.cases), 30)
        for f in range(5):
            seen = {}
            for q in b.questions:
                phase = partition(b, q, fold=f, folds=5)
                self.assertEqual(seen.setdefault(q.family, phase), phase)
            self.assertEqual(set(seen.values()), {"train", "select", "test"})
        self.assertEqual(aggregate(plan, receipts(plan), execution_binding={"code": "pinned"})["native_cases"], 30)

    def test_longmemeval_never_trains_on_its_own_test_targets(self):
        b = benchmark("longmemeval")
        plan = plan_coverage(b, folds=1, shards=4, per_fold_limit=None)
        self.assertEqual(len(plan.cases), 30)
        with self.assertRaises(ValueError):
            plan_coverage(b, folds=5, shards=4, per_fold_limit=None)

    def test_missing_duplicate_or_drifted_shard_is_not_success(self):
        plan = plan_coverage(benchmark(), folds=5, shards=2, per_fold_limit=None)
        cases = receipts(plan)
        variants = [cases[:-1], cases + cases[:1]]
        drifted = copy.deepcopy(cases)
        drifted[0]["execution_binding"] = {"code": "different"}
        variants.append(drifted)
        missing = copy.deepcopy(cases)
        missing[0]["results"]["rag"].pop()
        variants.append(missing)
        for variant in variants:
            with self.assertRaises(ValueError):
                aggregate(plan, variant, execution_binding={"code": "pinned"})

    def test_failures_stay_in_the_planned_denominator(self):
        plan = plan_coverage(benchmark(), folds=5, shards=2, per_fold_limit=None)
        cases = receipts(plan)
        cases[0]["results"]["rag"][0].update(status="failed", hypothesis=None, diagnostic_token_f1=None)
        result = aggregate(plan, cases, execution_binding={"code": "pinned"})
        self.assertEqual(result["arms"]["rag"]["planned"], 30)
        self.assertEqual(result["arms"]["rag"]["failed"], 1)
        self.assertEqual(result["arms"]["rag"]["diagnostic_f1_conditional_mean"], 0.5)
        self.assertLess(result["arms"]["rag"]["diagnostic_f1_zero_for_unscored_lower_summary"], 0.5)
        self.assertFalse(result["superiority_claim"])

    def test_global_pilot_limit_does_not_multiply_by_the_shard_count(self):
        b = benchmark("longmemeval")
        one = plan_coverage(b, folds=1, shards=1, per_fold_limit=7)
        four = plan_coverage(b, folds=1, shards=4, per_fold_limit=7)
        self.assertEqual({c[0] for c in one.cases}, {c[0] for c in four.cases})
        self.assertEqual(len(four.cases), 7)

    def test_manifest_roundtrip_and_pilot_are_not_full_benchmark(self):
        plan = plan_coverage(benchmark("longmemeval"), folds=1, shards=2, per_fold_limit=7)
        self.assertEqual(decode_plan(plan.content()), plan)
        result = aggregate(plan, receipts(plan), execution_binding={"code": "pinned"})
        self.assertTrue(result["complete"])
        self.assertFalse(result["all_native_questions_covered"])
        self.assertEqual(result["native_question_total"], 30)
        for bad in [{**plan.content(), "unknown": 1}, {**plan.content(), "folds": True},
                    {**plan.content(), "cases": list(plan.cases) * 2}]:
            with self.assertRaises(ValueError):
                decode_plan(bad)
