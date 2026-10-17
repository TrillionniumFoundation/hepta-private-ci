from pathlib import Path
import hashlib
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "stem-transfer-cell-artifact-p0"))

from neuron_shared_encoder.stem_bridge import (  # noqa: E402
    ArtifactIdentityV1,
    FeatureKeyV1,
    QualificationReceiptV1,
    ReaderGateReceiptV1,
    feature_key_for_artifact,
    transfer_matrix_from_receipts,
)
from stem_transfer_cell_artifact import CellArtifactV1, ContractError, StemManifestV1  # noqa: E402


def digest(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


STEM = StemManifestV1(
    stem_id="stem.shared.v1",
    stem_digest=digest("stem"),
    tokenizer_digest=digest("tokenizer"),
    preprocessor_digest=digest("preprocessor"),
    adapter_basis_digest=digest("basis"),
    hidden_width=1024,
    modality_projectors=("audio", "image", "text", "video"),
)

CELL = CellArtifactV1(
    cell_id="cell.reader.v1",
    parent_cell_id=None,
    stem_digest=STEM.stem_digest,
    adapter_basis_digest=STEM.adapter_basis_digest,
    adapter_rank=8,
    layer_mask=(4, 8),
    head_digest=digest("head"),
    memory_schema_digest=digest("memory"),
    state_namespace="reader.state.v1",
    objective_digest=digest("objective"),
    generation=1,
)


def identity(**overrides):
    values = dict(
        stem_digest=STEM.stem_digest,
        stem_generation=0,
        cell_generation=1,
        run_generation=1,
        authority_epoch="epoch.1",
        principal="research",
        purpose="qualification",
        source_digest=digest("source"),
        input_digest=digest("input"),
        preprocessor_digest=STEM.preprocessor_digest,
    )
    values.update(overrides)
    return ArtifactIdentityV1(**values)


def receipt(**overrides):
    values = dict(
        task_id="task.reader.a",
        modality="text",
        stem_digest=STEM.stem_digest,
        source_digest=digest("source"),
        budget_digest=digest("budget"),
        quality=0.8,
        flops=10,
        memory_bytes=20,
        latency_ms=2,
        risk=0.01,
        stem_params=100,
        projector_params=10,
        resident_cell_params=20,
        active_cell_params=8,
        state_params=2,
        cache_params=1,
        logical_cells=64,
        active_cells=1,
        evidence_class="REAL_SHADOW",
        independent_new_source=True,
        reader_citations=4,
    )
    values.update(overrides)
    return QualificationReceiptV1(**values)


class StemBridgeTests(unittest.TestCase):
    def test_feature_key_requires_positive_run_generation(self):
        with self.assertRaises(ContractError):
            identity(run_generation=0)

    def test_feature_key_binds_cell_generation_and_stem(self):
        key = feature_key_for_artifact(CELL, identity())
        self.assertEqual(key.cell_generation, CELL.generation)
        self.assertTrue(key.readonly)
        with self.assertRaises(ContractError):
            feature_key_for_artifact(CELL, identity(stem_digest=digest("other")))

    def test_feature_key_rejects_stale_cell_generation(self):
        with self.assertRaises(ContractError):
            feature_key_for_artifact(CELL, identity(cell_generation=0))

    def test_receipt_ledger_counts_projector_and_cell_parameters(self):
        ledger = receipt().to_ledger()
        self.assertEqual(ledger.logical_params, 133)
        self.assertEqual(ledger.active_params, 121)

    def test_incomplete_receipt_is_preserved_and_cannot_be_zero_filled(self):
        incomplete = receipt(stem_params=None, receipt_status="INCOMPLETE", missing_fields=("stem_params",))
        with self.assertRaises(ContractError):
            incomplete.to_ledger()
        with self.assertRaises(ContractError):
            incomplete.to_transfer_case()

    def test_complete_receipt_cannot_hide_a_missing_field(self):
        with self.assertRaises(ContractError):
            receipt(stem_params=None)

    def test_transfer_matrix_rejects_budget_mismatch(self):
        with self.assertRaises(ContractError):
            transfer_matrix_from_receipts(STEM, (receipt(), receipt(task_id="task.reader.b", budget_digest=digest("other-budget"))), digest("budget"))

    def test_transfer_matrix_keeps_one_frozen_stem(self):
        matrix = transfer_matrix_from_receipts(STEM, (receipt(), receipt(task_id="task.reader.b")), digest("budget"))
        self.assertEqual(matrix.stem.stem_digest, STEM.stem_digest)
        self.assertEqual(len(matrix.cases), 2)

    def test_synthetic_reader_receipt_cannot_pass_split_gate(self):
        gate = ReaderGateReceiptV1("SYNTHETIC_SMOKE", True, True, 1.0, 0.9, 0.8, 0.01, 0.02, 0.001, 1.0, 1.0, 0).to_split_gate()
        self.assertFalse(gate.passes)
        self.assertIn("reader_evidence_insufficient", gate.reasons())

    def test_historical_replay_cannot_pass_split_gate(self):
        gate = ReaderGateReceiptV1("HISTORICAL_REPLAY", True, True, 1.0, 0.9, 0.8, 0.01, 0.02, 0.001, 1.0, 1.0, 0).to_split_gate()
        self.assertFalse(gate.passes)

    def test_real_reader_receipt_can_become_a_candidate_gate(self):
        gate = ReaderGateReceiptV1("REAL_SHADOW", True, True, 1.0, 0.9, 0.8, 0.01, 0.02, 0.001, 1.0, 1.0, 0).to_split_gate()
        self.assertTrue(gate.passes)

    def test_gold_visible_to_model_is_rejected(self):
        with self.assertRaises(ContractError):
            receipt(model_input_gold_visible=True)
        with self.assertRaises(ContractError):
            ReaderGateReceiptV1("REAL_SHADOW", True, True, 1.0, 0.9, 0.8, 0.01, 0.02, 0.001, 1.0, 1.0, 0, True)

    def test_incomplete_reader_evidence_cannot_become_a_gate(self):
        evidence = ReaderGateReceiptV1(
            "INCOMPLETE", True, False, None, None, None, None, None, None, None, None, None,
            missing_fields=("baseline_ucb", "citation_coverage", "deleted_replay", "ece", "fallback_coverage", "future_lcb", "old_task_degradation", "ood_false_acceptance", "rollback_recovery"),
        )
        with self.assertRaises(ContractError):
            evidence.to_split_gate()


if __name__ == "__main__":
    unittest.main()
