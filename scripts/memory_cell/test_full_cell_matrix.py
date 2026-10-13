import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from full_cell_matrix import evaluate_reader_gate, enumerate_matrix, plan, resource_estimate


def gate_fixture():
    trust = {
        "schema": "hepta.reader.trust.v1",
        "independent_reviewers": [{"id": "reviewer-a", "revoked": False}],
    }
    trust_digest = hashlib.sha256(
        json.dumps(trust, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    ids = [f"q-{i}" for i in range(20)]
    binding = {
        name: f"{chr(97 + index) * 64}"
        for index, name in enumerate(
            ("weights_sha256", "tokenizer_sha256", "prompt_sha256", "dataset_sha256")
        )
    }
    binding.update(revision="model-r1", decode_budget=64)
    gate = {
        "schema": "hepta.reader-gate.v2",
        "cohort": ids,
        "model_binding": binding,
        "independent_review": {"trust_manifest_sha256": trust_digest},
        "capabilities": {"modalities": ["text"], "inference": ["no_recurrent"]},
        "conditions": {
            "no_evidence": {"item_ids": ids, "total": 20, "grounded_and_cited": 0, "exact_refusal": 19},
            "ordinary_retrieval": {"item_ids": ids, "total": 20, "grounded_and_cited": 7, "exact_refusal": 3},
            "human_sufficient": {"item_ids": ids, "total": 20, "grounded_and_cited": 18, "exact_refusal": 0},
            "critical_premise_removed": {"item_ids": ids, "total": 20, "grounded_and_cited": 0, "exact_refusal": 20},
        },
    }
    return gate, trust


class FullCellMatrixTests(unittest.TestCase):
    def test_matrix_has_all_declared_axes(self):
        rows = enumerate_matrix(cells=4)
        self.assertEqual(len(rows), 4 * 4 * 4 * 4 * 3)
        self.assertEqual(len({row["config_id"] for row in rows}), len(rows))

    def test_resource_estimate_does_not_call_nominal_parameters_flops(self):
        row = resource_estimate(
            "shared_421m_plus_head", "gated", "video", "system2_ndu", "split_merge", 32
        )
        self.assertIsNone(row["active_flops"])
        self.assertIsNone(row["peak_memory_bytes"])
        self.assertIsNone(row["energy_joules"])
        self.assertEqual(row["parameter_budget"]["incremental_cell_parameters"], 2_000_000)

    def test_replicated_stem_costs_more_than_shared(self):
        shared = resource_estimate("shared_421m_plus_head", "gated", "text", "no_recurrent", "no_split", 32)
        copied = resource_estimate("replicated_421m", "gated", "text", "no_recurrent", "no_split", 32)
        self.assertGreater(
            copied["parameter_budget"]["unique_parameters"],
            shared["parameter_budget"]["unique_parameters"] * 20,
        )

    def test_reader_gate_requires_external_model_bound_trust_and_same_cohort(self):
        gate, trust = gate_fixture()
        self.assertTrue(evaluate_reader_gate(gate, trust).passed)
        self.assertFalse(evaluate_reader_gate(gate).passed)
        gate["conditions"]["ordinary_retrieval"]["item_ids"] = ["different"] * 20
        self.assertFalse(evaluate_reader_gate(gate, trust).passed)

    def test_unqualified_plan_blocks_every_record_and_leaves_scores_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            summary = plan(Path(directory), cells=2)
            self.assertEqual(summary["blocked_reader_records"], 768)
            self.assertEqual(summary["neural_calls"], 0)
            rows = [
                json.loads(line)
                for line in (Path(directory) / "matrix-plan.jsonl").read_text().splitlines()
            ]
            self.assertTrue(all(row["status"] == "blocked_reader_gate" for row in rows))
            self.assertTrue(all(value is None for row in rows for value in row["metrics"].values()))

    def test_passed_reader_gate_only_admits_bound_capability(self):
        gate, trust = gate_fixture()
        with tempfile.TemporaryDirectory() as directory:
            summary = plan(Path(directory), cells=2, reader_gate=gate, trust_manifest=trust)
            self.assertEqual(summary["planned_neural_records"], 48)
            self.assertEqual(summary["blocked_capability_records"], 720)


if __name__ == "__main__":
    unittest.main()
