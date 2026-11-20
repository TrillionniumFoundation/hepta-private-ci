"""Check that retrieval sees training references and the query input only."""

import copy
import json
from pathlib import Path
import unittest

from . import data
from .circuit_repair_study_v4 import prepare, retrieve

ROOT = Path(__file__).resolve().parents[2]


class RetrievalControls(unittest.TestCase):
    def test_fixed_training_memory_and_live_verifications(self):
        records = [
            (name, row)
            for name in ("c", "d")
            for row in data.load_records(
                ROOT
                / "qualification/cell-diagnostic-panel-20261118"
                / name
                / "prepared-records.jsonl"
            )
        ]
        arms, augmented, study = prepare(records, ROOT)
        self.assertEqual(len(arms) * len(records) * 2, 88)
        self.assertEqual(study["reference_verifier_calls"], 6)
        self.assertTrue(all(row["success"] for row in study["reference_verifications"]))
        self.assertEqual(len(augmented), 4)
        for panel, row in records:
            got = augmented[(panel, row["record_id"])]
            self.assertEqual(got["task"]["input"], row["task"]["input"])
            self.assertEqual(got["task"]["verifier"], row["task"]["verifier"])
            payload = json.loads(got["task"]["messages"][-1]["content"])
            self.assertNotEqual(payload["task"], row["task"]["input"])
            self.assertNotEqual(payload["answer"], row["final_answer"])

    def test_selection_ignores_evaluation_answer_and_memory_order(self):
        rows = data.load_records(
            ROOT
            / "qualification/cell-experiments-v3-20261116/development-old-open.records.jsonl"
        )
        memory = [row for row in rows if row["split"] == "train"]
        query = copy.deepcopy(rows[-1])
        first, receipt = retrieve(query, memory)
        query["final_answer"] = "MUST_NOT_REACH_RETRIEVAL"
        query["trajectory"] = []
        second, changed = retrieve(query, list(reversed(memory)))
        self.assertEqual(first["task"]["messages"], second["task"]["messages"])
        self.assertEqual(
            receipt["memory_record_digest"], changed["memory_record_digest"]
        )
        self.assertNotIn(
            "MUST_NOT_REACH_RETRIEVAL",
            data.canonical(second["task"]["messages"]).decode(),
        )


if __name__ == "__main__":
    unittest.main()
