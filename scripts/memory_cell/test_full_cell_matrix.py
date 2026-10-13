import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from full_cell_matrix import evaluate_reader_gate, enumerate_matrix, plan, resource_estimate


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def gate_fixture():
    trust = {
        "schema": "hepta.reader.trust.v1",
        "independent_reviewers": [{"id": "reviewer-a", "revoked": False}],
    }
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
        "independent_review": {"trust_manifest_sha256": ""},
        "capabilities": {"modalities": ["text"], "inference": ["no_recurrent"]},
        "conditions": {
            "no_evidence": {"item_ids": ids, "total": 20, "grounded_and_cited": 0, "exact_refusal": 19},
            "ordinary_retrieval": {"item_ids": ids, "total": 20, "grounded_and_cited": 7, "exact_refusal": 3},
            "human_sufficient": {"item_ids": ids, "total": 20, "grounded_and_cited": 18, "exact_refusal": 0},
            "critical_premise_removed": {"item_ids": ids, "total": 20, "grounded_and_cited": 0, "exact_refusal": 20},
        },
    }
    reviewed = {
        name: gate[name] for name in (
            "schema", "cohort", "model_binding", "conditions", "capabilities"
        )
    }
    trust["reviewed_gate_content_sha256"] = fingerprint(reviewed)
    gate["independent_review"]["trust_manifest_sha256"] = fingerprint(trust)
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
        self.assertFalse(evaluate_reader_gate(gate, trust).passed)
        self.assertTrue(evaluate_reader_gate(
            gate, trust, trusted_review_sha256=fingerprint(trust)
        ).passed)
        self.assertFalse(evaluate_reader_gate(gate).passed)
        gate["conditions"]["ordinary_retrieval"]["item_ids"] = ["different"] * 20
        self.assertFalse(evaluate_reader_gate(gate, trust).passed)

    def test_self_attested_manifest_alone_never_enables_model_experiments(self):
        gate, trust = gate_fixture()
        self.assertEqual(evaluate_reader_gate(gate, trust).reason,
                         "out-of-band-trust-pin-required")
        self.assertEqual(evaluate_reader_gate(
            gate, trust, trusted_review_sha256="a" * 64
        ).reason, "out-of-band-trust-pin-mismatch")
        with tempfile.TemporaryDirectory() as directory:
            summary = plan(Path(directory), cells=2,
                           reader_gate=gate, trust_manifest=trust)
            self.assertEqual(summary["blocked_reader_records"], 768)
            self.assertEqual(summary["planned_neural_records"], 0)

    def test_edited_scores_are_not_the_same_independent_review(self):
        gate, trust = gate_fixture()
        approved = fingerprint(trust)
        forged = copy.deepcopy(gate)
        forged["conditions"]["human_sufficient"]["grounded_and_cited"] = 20
        self.assertEqual(evaluate_reader_gate(
            forged, trust, trusted_review_sha256=approved
        ).reason, "review-not-bound-to-observed-reader-results")
        altered = copy.deepcopy(trust)
        reviewed = {name: forged[name] for name in (
            "schema", "cohort", "model_binding", "conditions", "capabilities"
        )}
        altered["reviewed_gate_content_sha256"] = fingerprint(reviewed)
        forged["independent_review"]["trust_manifest_sha256"] = fingerprint(altered)
        self.assertEqual(evaluate_reader_gate(
            forged, altered, trusted_review_sha256=approved
        ).reason, "out-of-band-trust-pin-mismatch")

    def test_forged_capability_and_duplicate_reviewer_are_rejected(self):
        gate, trust = gate_fixture()
        bad = copy.deepcopy(gate)
        bad["capabilities"]["modalities"] = ["text", "text"]
        self.assertEqual(evaluate_reader_gate(
            bad, trust, trusted_review_sha256=fingerprint(trust)
        ).reason, "invalid-reader-capabilities")
        double = copy.deepcopy(trust)
        double["independent_reviewers"].append(copy.deepcopy(double["independent_reviewers"][0]))
        gated = copy.deepcopy(gate)
        gated["independent_review"]["trust_manifest_sha256"] = fingerprint(double)
        self.assertEqual(evaluate_reader_gate(
            gated, double, trusted_review_sha256=fingerprint(double)
        ).reason, "no-current-independent-reviewer-in-trust-manifest")

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
            summary = plan(
                Path(directory), cells=2, reader_gate=gate, trust_manifest=trust,
                trusted_review_sha256=fingerprint(trust),
            )
            self.assertEqual(summary["planned_neural_records"], 48)
            self.assertEqual(summary["blocked_capability_records"], 720)


if __name__ == "__main__":
    unittest.main()
