"""Actual tensor serialization regression; pretrained network is NEVER mocked as real.

Uses a deterministic 768D test double only for the *negative/serialization*
unit suite. The separate hosted integration job must invoke LocalHFEncoder and
physically load the pinned complete ModernBERT checkpoint on BANKING77.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import torch
from safetensors.torch import load_file

from public_q24_feature_snapshot import (
    Q, FEAT_WIDTH, FIT, HELDOUT, MODEL_REV, DATA_REV,
    fit_training_pca32, project_q24, physical_snapshot,
)
from public_cell_learning import validate_inputs
from next_round_matrix import _digest


class DeterministicFixture:
    dimension = FEAT_WIDTH
    def __init__(self):
        self.calls = []
        self.verifications = 0
        self.receipt = {
            "snapshot_sha256": "a" * 64,
            "pretrained_provenance_independently_verified": False,
            "source_kind": "EXPLICIT_SYNTHETIC_UNIT_ONLY",
        }

    def encode(self, row):
        self.calls.append(copy.deepcopy(row))
        seed = int.from_bytes(
            hashlib.sha256(row["state"].encode("utf-8")).digest()[:8],
            "big",
        ) % (2**63 - 1)
        generator = torch.Generator().manual_seed(seed)
        return torch.randn(FEAT_WIDTH, generator=generator).float() * 0.25, 16

    def reverify(self):
        self.verifications += 1


def fixed_inputs():
    fits = [{"id": f"fit:{i:064x}",
             "text": f"Public training phrase about intent class {i % 4}: {i}",
             "label": i % 4} for i in range(FIT)]
    heldouts = [{"id": f"heldout:{i:064x}",
                 "text": f"Official test phrase from different original split {i}"}
                for i in range(HELDOUT)]
    value = {"schema": "hepta.banking77-four-intent-inputs.v1",
             "intents": [
                 "card_arrival", "cash_withdrawal_not_recognised",
                 "exchange_rate", "lost_or_stolen_phone",
             ],
             "fit": fits, "heldout": heldouts}
    value["input_id"] = _digest(value)
    validate_inputs(value)
    return value


class PublicQ24SnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.workspace.cleanup)
        cls.root = Path(cls.workspace.name) / "snapshot"
        cls.inputs = fixed_inputs()
        cls.backend = DeterministicFixture()
        cls.receipt = physical_snapshot(cls.inputs, cls.backend, cls.root)

    def test_actual_tensor_files_created_with_exact_dimensions_and_replayed(self):
        original = load_file(str(self.root / "pooled-f32.safetensors"))
        proj = load_file(str(self.root / "train-only-pca32.safetensors"))
        quant = load_file(str(self.root / "feature-q24.safetensors"))
        self.assertEqual(original["fit"].shape, (FIT, FEAT_WIDTH))
        self.assertEqual(original["heldout"].shape, (HELDOUT, FEAT_WIDTH))
        self.assertEqual(proj["components"].shape, (FEAT_WIDTH, 32))
        self.assertEqual(proj["center"].shape, (FEAT_WIDTH,))
        self.assertEqual(proj["scale"].shape, (32,))
        self.assertEqual(quant["fit"].shape, (FIT, 32))
        self.assertEqual(quant["heldout"].shape, (HELDOUT, 32))
        self.assertEqual(quant["fit"].dtype, torch.int64)
        for split in ("fit", "heldout"):
            replay, clipped = project_q24(original[split], proj)
            self.assertTrue(torch.equal(replay, quant[split]))
            self.assertTrue(0 <= clipped <= original[split].shape[0] * 32)

    def test_one_encoder_pass_never_sees_heldout_labels(self):
        self.assertEqual(self.backend.verifications, 1)
        self.assertEqual(len(self.backend.calls), 96)
        self.assertTrue(all(set(row) == {"state", "question", "options"}
                            and "label" not in row for row in self.backend.calls))
        self.assertEqual(self.receipt["physical_encoder_forward_calls_this_snapshot"], 96)
        self.assertEqual(self.receipt["source_class"], "SYNTHETIC_UNIT_FIXTURE_ONLY")

    def test_registry_separates_train_labels_and_test_inputs(self):
        registry = json.loads((self.root / "case-registry.json").read_text())
        self.assertEqual(len(registry["fit"]), 64)
        self.assertEqual(len(registry["heldout"]), 32)
        self.assertTrue(all(type(row["label"]) is int for row in registry["fit"]))
        self.assertTrue(all(set(row) == {"id"} for row in registry["heldout"]))
        self.assertEqual(registry["input_id"], self.inputs["input_id"])
        self.assertTrue(registry["no_future_window_claim"])
        self.assertFalse(self.receipt["future_window_utility_verified"])
        self.assertFalse(self.receipt["production_qualification"])

    def test_projection_only_depends_on_training_features(self):
        original = load_file(str(self.root / "pooled-f32.safetensors"))
        saved = load_file(str(self.root / "train-only-pca32.safetensors"))
        fit_again = fit_training_pca32(original["fit"])
        for name in saved:
            self.assertTrue(torch.equal(saved[name], fit_again[name]))
        # A grossly changed heldout distribution does NOT refit the PCA32 basis.
        fake_test = original["heldout"] + 400
        fake_q24, _ = project_q24(fake_test, saved)
        self.assertEqual(fake_q24.shape, (32, 32))
        after_fit = fit_training_pca32(original["fit"])
        self.assertTrue(all(torch.equal(saved[k], after_fit[k]) for k in saved))

    def test_no_hidden_labels_can_be_injected_into_encoder(self):
        edited = copy.deepcopy(self.inputs)
        edited["heldout"][0]["label"] = 1
        edited["input_id"] = _digest({k: v for k, v in edited.items() if k != "input_id"})
        with tempfile.TemporaryDirectory() as tmp:
            backend = DeterministicFixture()
            with self.assertRaises(ValueError):
                physical_snapshot(edited, backend, Path(tmp) / "denied")
            self.assertEqual(backend.calls, [])

    def test_source_identity_must_be_real_when_claimed(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = {"model_revision": MODEL_REV, "dataset_revision": DATA_REV,
                    "snapshot_sha256": "b" * 64}
            backend = DeterministicFixture()
            with self.assertRaises(ValueError):
                physical_snapshot(self.inputs, backend, Path(tmp) / "refused",
                                  source_identity=fake)
            self.assertEqual(backend.calls, [])

    def test_rank_failure_is_fatal(self):
        rank_deficient = torch.zeros((FIT, FEAT_WIDTH), dtype=torch.float32)
        with self.assertRaisesRegex(ValueError, "rank"):
            fit_training_pca32(rank_deficient)

    def test_out_of_range_feature_and_dimension_rejected(self):
        with self.assertRaises(ValueError):
            project_q24(torch.zeros((3, FEAT_WIDTH + 1)),
                        load_file(str(self.root / "train-only-pca32.safetensors")))
        invalid = torch.zeros((FIT, FEAT_WIDTH))
        invalid[0, 0] = float("nan")
        with self.assertRaises(ValueError):
            fit_training_pca32(invalid)

    def test_snapshot_is_immutable_create_once(self):
        with self.assertRaises(FileExistsError):
            physical_snapshot(self.inputs, DeterministicFixture(), self.root)

    def test_digest_and_no_authority(self):
        receipt = json.loads((self.root / "SEALED.json").read_text())
        self.assertEqual(receipt, self.receipt)
        for filename, stored in receipt["files"].items():
            raw = (self.root / filename).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), stored["sha256"])
            self.assertEqual(len(raw), stored["bytes"])
        self.assertFalse(receipt["no_change_production_v1_baseline_verified"])
        self.assertFalse(receipt["ndu_eligible"])
        self.assertEqual(receipt["decision"], "NO_MODEL_PROMOTION")


if __name__ == "__main__":
    unittest.main()
