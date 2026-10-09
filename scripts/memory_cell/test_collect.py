"""Collector tests validate predeclared coverage, not model quality or authority."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from benchmark_collect import collect
from benchmark_coverage import plan_coverage
from test_coverage import benchmark, receipts


class CollectorTests(unittest.TestCase):
    def test_collector_uses_external_plan_and_retains_explicit_failure(self):
        plan = plan_coverage(
            benchmark("longmemeval"), folds=1, shards=2, per_fold_limit=7
        )
        records = receipts(plan)
        records[0]["results"]["rag"][0].update(
            status="failed", hypothesis=None, diagnostic_token_f1=None
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            declared = root / "predeclared.json"
            declared.write_text(
                json.dumps(
                    {
                        "schema": "hepta.memory-benchmark.preregistered.v1",
                        "coverage": plan.content(),
                        "execution_binding": {"code": "pinned"},
                    }
                )
            )
            for i, value in enumerate(records):
                shard = root / "shards" / str(i)
                shard.mkdir(parents=True)
                (shard / "report.json").write_text(json.dumps(value))
            result = collect(declared, root / "shards", root / "complete.json")
            self.assertEqual(result["arms"]["rag"]["planned"], 7)
            self.assertEqual(result["arms"]["rag"]["failed"], 1)
            self.assertFalse(result["all_native_questions_covered"])
            self.assertEqual(json.loads((root / "complete.json").read_text()), result)
            with self.assertRaises(FileExistsError):
                collect(declared, root / "shards", root / "complete.json")
            (root / "shards" / "1" / "report.json").unlink()
            with self.assertRaises(ValueError):
                collect(declared, root / "shards", root / "incomplete.json")
            self.assertFalse((root / "incomplete.json").exists())

    def test_invalid_native_outcomes_cannot_become_scored_successes(self):
        from benchmark_coverage import aggregate

        plan = plan_coverage(
            benchmark("longmemeval"), folds=1, shards=1, per_fold_limit=7
        )
        for update in (
            {"diagnostic_token_f1": float("nan")},
            {"diagnostic_token_f1": True},
            {"status": "failed", "diagnostic_token_f1": 1.0},
            {"status": "succeeded", "hypothesis": None},
            {"status": "queued"},
        ):
            records = copy.deepcopy(receipts(plan))
            records[0]["results"]["rag"][0].update(update)
            with self.assertRaises(ValueError):
                aggregate(plan, records, execution_binding={"code": "pinned"})
