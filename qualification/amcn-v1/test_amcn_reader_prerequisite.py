"""Fail-closed delegation to the existing externally signed Reader owner."""
from dataclasses import dataclass
from unittest.mock import patch
import sys
import types
import unittest
from amcn_core import digest, Refused
from amcn_reader_prerequisite import reader_prerequisite


@dataclass(frozen=True)
class Gate:
    passed: bool = False
    reason: str = "out-of-band-trust-pin-required"
    cohort_size: int = 0
    human_sufficient_grounded: int = 0
    ordinary_retrieval_grounded: int = 0
    no_evidence_exact_refusal: int = 0
    premise_removed_exact_refusal: int = 0
    model_binding_digest: str | None = None
    capabilities: dict | None = None


def fake_full_cell_matrix(gate):
    root = types.ModuleType("scripts")
    package = types.ModuleType("scripts.memory_cell")
    module = types.ModuleType("scripts.memory_cell.full_cell_matrix")
    module.evaluate_reader_gate = lambda *a, **kw: gate
    return {"scripts": root, "scripts.memory_cell": package,
            "scripts.memory_cell.full_cell_matrix": module}


class ReaderPrerequisiteTests(unittest.TestCase):
    def test_no_self_issued_trust_or_production_grant(self):
        with patch.dict(sys.modules, fake_full_cell_matrix(Gate())):
            packet = reader_prerequisite()
        m = packet["metrics"]
        self.assertEqual(m["disposition"], "blocked_reader_adequacy")
        self.assertFalse(packet["production_accepted"])
        self.assertFalse(m["may_split_or_merge_product_cells"])
        self.assertFalse(m["may_train_new_semantic_head_for_product"])
        self.assertFalse(m["may_scale_cell_population"])

    def test_signed_reader_with_retrieval_gap_remains_research_only(self):
        bundle = {"weights_sha256": "a"*64, "decoder": 256}
        key = digest(bundle)
        gate = Gate(True, "passed", 20, 18, 7, 19, 19, key,
                    {"modalities": ["text"], "inference": ["no_recurrent"]})
        with patch.dict(sys.modules, fake_full_cell_matrix(gate)):
            report = reader_prerequisite(
                gate_receipt={"model_binding": bundle},
                externally_pinned_trust_sha256="b"*64,
                externally_pinned_roster_sha256="c"*64,
                expected_model_binding_sha256=key,
                original_answers_sha256="d"*64,
                original_judgments_sha256="e"*64,
            )
        self.assertEqual(report["metrics"]["disposition"],
                         "reader_adequate_with_retrieval_headroom_research_only")
        self.assertTrue(report["metrics"]["existing_reader_gate_passed"])
        self.assertFalse(report["production_accepted"])
        self.assertFalse(report["metrics"]["originals_independently_reopened_by_this_module"])
        self.assertEqual(report["metrics"]["physical_reader_generations_executed"], 0)

    def test_reader_adequacy_alone_does_not_imply_retrieval_headroom(self):
        binding = {"weights_sha256": "f"*64}
        key = digest(binding)
        gate = Gate(True, "passed", 20, 18, 18, 19, 19, key, {"modalities": ["text"]})
        with patch.dict(sys.modules, fake_full_cell_matrix(gate)):
            report = reader_prerequisite(
                gate_receipt={"model_binding": binding},
                externally_pinned_trust_sha256="a"*64,
                externally_pinned_roster_sha256="b"*64,
                expected_model_binding_sha256=key,
                original_answers_sha256="c"*64,
                original_judgments_sha256="d"*64)
        self.assertEqual(report["metrics"]["disposition"],
                         "reader_adequate_but_no_retrieval_headroom")

    def test_exact_model_or_original_digest_required(self):
        binding = {"weights_sha256": "f"*64}
        key = digest(binding)
        gate = Gate(True, "passed", 20, 18, 6, 19, 19, key, {"modalities": ["text"]})
        with patch.dict(sys.modules, fake_full_cell_matrix(gate)):
            result = reader_prerequisite(
                gate_receipt={"model_binding": binding},
                expected_model_binding_sha256="0"*64,
                original_answers_sha256="c"*64,
                original_judgments_sha256="d"*64)
            self.assertEqual(result["metrics"]["disposition"], "blocked_model_binding")
            result2 = reader_prerequisite(
                gate_receipt={"model_binding": binding},
                expected_model_binding_sha256=key)
            self.assertEqual(result2["metrics"]["disposition"],
                             "blocked_original_answers_or_judgments")
            with self.assertRaises(Refused):
                reader_prerequisite(expected_model_binding_sha256="nonhash")


if __name__ == "__main__":
    unittest.main()
