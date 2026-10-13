import json
from pathlib import Path
import tempfile
import unittest

from full_cell_matrix import (
    evaluate_reader_gate,
    enumerate_matrix,
    plan,
    resource_estimate,
)


class FullCellMatrixTests(unittest.TestCase):
    def test_matrix_has_all_declared_axes(self):
        rows = enumerate_matrix(cells=4)
        self.assertEqual(len(rows), 4 * 4 * 4 * 4 * 3)
        self.assertEqual(len({row["config_id"] for row in rows}), len(rows))

    def test_replicated_stem_costs_more_than_shared(self):
        shared = resource_estimate("shared_421m", "gated", "text", "no_recurrent", "no_split", 32)
        copied = resource_estimate("replicated_421m", "gated", "text", "no_recurrent", "no_split", 32)
        self.assertGreater(copied["unique_params"], shared["unique_params"] * 20)

    def test_reader_gate_requires_independent_sufficient_controls(self):
        self.assertFalse(evaluate_reader_gate(None).passed)
        payload = {
            "schema": "hepta.reader-gate.v1",
            "independent_adjudication": True,
            "reader_adequacy_established": True,
            "conditions": {
                "human_sufficient": {"grounded": 18},
                "ordinary_retrieval": {"grounded": 7},
                "no_evidence": {"exact_refusal": 19},
                "critical_premise_removed": {"exact_refusal": 20},
            },
        }
        self.assertTrue(evaluate_reader_gate(payload).passed)

    def test_unqualified_plan_blocks_every_record_and_leaves_scores_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            summary = plan(Path(directory), cells=2)
            self.assertEqual(summary["blocked_records"], 768)
            self.assertEqual(summary["neural_calls"], 0)
            rows = [json.loads(line) for line in (Path(directory) / "matrix-plan.jsonl").read_text().splitlines()]
            self.assertTrue(all(row["status"] == "blocked_reader_gate" for row in rows))
            self.assertTrue(all(value is None for row in rows for value in row["metrics"].values()))


if __name__ == "__main__":
    unittest.main()
