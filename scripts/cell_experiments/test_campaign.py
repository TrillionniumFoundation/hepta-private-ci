"""Controls for frozen records and deterministic routing-label interpretation."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from .campaign import json_value_domain, frozen_plan, retrieve
from .data import digest


class CampaignTests(unittest.TestCase):
    def test_boolean_is_not_misclassified_as_integer(self):
        self.assertEqual(
            [
                json_value_domain(s)
                for s in [
                    '{"x":2}',
                    '{"x":false}',
                    '{"x":2,"y":true}',
                    "{}",
                    "[]",
                    "invalid",
                ]
            ],
            [0, 1, 1, 2, 2, 2],
        )
        self.assertEqual(
            [
                json_value_domain(s)
                for s in ['{"x":NaN}', '{"x":1e999}', '{"x":0,"x":true}']
            ],
            [2, 2, 2],
        )

    def test_retrieval_cannot_use_the_probe_answer(self):
        examples = [
            {
                "record_id": "a",
                "task": {"input": "count valid receipts"},
                "final_answer": "training",
            },
            {
                "record_id": "b",
                "task": {"input": "model dimension"},
                "final_answer": "another",
            },
        ]
        query = {"task": {"input": "count receipts"}, "final_answer": "PRIVATE"}
        before = copy.deepcopy(query)
        augmented, selected = retrieve(examples, query)
        self.assertEqual(selected, "a")
        self.assertNotIn("PRIVATE", augmented["task"]["input"])
        self.assertEqual(query, before)

    def test_plan_freezes_actual_subset_and_mode(self):
        records = [
            {"task_id": str(n), "source_id": str(n), "split": split}
            for n, split in enumerate(("train", "selection", "confirmation"))
        ]
        with tempfile.TemporaryDirectory() as temporary:
            plan = frozen_plan(
                records,
                records[:1],
                {"runtime": {}},
                temporary,
                "trajectory",
                "a" * 64,
                2,
            )
            saved = json.loads((Path(temporary) / "plans/trajectory.json").read_text())
            self.assertEqual(saved, plan)
            self.assertEqual(plan["training_records_digest"], digest(records[:1]))
            self.assertEqual(plan["training_mode"], "trajectory")
            self.assertEqual(plan["evidence_scope"], "engineering")


if __name__ == "__main__":
    unittest.main()
