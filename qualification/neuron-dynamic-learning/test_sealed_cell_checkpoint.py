"""Synthetic in-memory SGD-compatible Cell double, never pretrained evidence."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np
from sealed_cell_checkpoint import (
    CheckpointError, _canonical, _sha, load_checkpoint, seal_checkpoint,
)


class FakeDynamicCell:
    def __init__(self, cell_id, encoder_digest, width, groups, rank, down, up,
                 gate_bias, cell_state, drive_weights, prediction_weights,
                 drive_bias=0.0, prediction_bias=0.0):
        self.cell_id = cell_id
        self.encoder_digest = encoder_digest
        self.width = width
        self.groups = groups
        self.rank = rank
        for name in ("down", "up", "gate_bias", "cell_state", "drive_weights", "prediction_weights"):
            setattr(self, name, np.asarray(locals()[name], dtype=np.float64))
        self.drive_bias = drive_bias
        self.prediction_bias = prediction_bias

    def parameter_count(self):
        return sum(np.asarray(getattr(self, k)).size for k in (
            "down", "up", "gate_bias", "cell_state", "drive_weights", "prediction_weights")) + 2

    def export_q24(self):
        return {"id": self.cell_id, "encoder_digest": self.encoder_digest,
                **{k: np.rint(np.asarray(getattr(self, k)).reshape(-1)*(1 << 24)).astype(int).tolist()
                   for k in ("down", "up", "gate_bias", "cell_state", "drive_weights", "prediction_weights")},
                "drive_bias": round(self.drive_bias*(1<<24)),
                "prediction_bias": round(self.prediction_bias*(1<<24))}

    def predict(self, x):
        x = np.asarray(x, dtype=np.float64)
        return x @ self.prediction_weights + self.prediction_bias


def fake_cell(variant: float = 0.0):
    rank, width, groups = 4, 256, 8
    return FakeDynamicCell(
        cell_id="shadow.agnews.binary", encoder_digest="a"*64,
        width=width, groups=groups, rank=rank,
        down=np.full((rank, width), 0.01, dtype=np.float64),
        up=np.full((groups, rank), -0.02, dtype=np.float64),
        gate_bias=np.zeros(groups), cell_state=np.zeros(groups),
        drive_weights=np.full(width, 0.003),
        prediction_weights=np.full(width, 0.004 + variant),
        drive_bias=0.0, prediction_bias=0.001 + variant,
    )


def fixture_args():
    return dict(source_panel_digest="b"*64, model_revision="c"*40,
                pipeline_digest="a"*64, scope_id="public.agnews",
                purpose_id="capability.noeffects", generation=1,
                authority_epoch=1, steps=40, seed=17)


class ShadowCheckpoint(unittest.TestCase):
    def setUp(self):
        self.modules = patch.dict(sys.modules, {
            "cell_learning": types.SimpleNamespace(
                DynamicCell=FakeDynamicCell,
                rust_candidate_digest=lambda x: _sha(_canonical(x)),
            ),
        })
        self.modules.start()

    def tearDown(self):
        self.modules.stop()

    def make(self, path):
        return seal_checkpoint(path, fake_cell(), fake_cell(0.002), **fixture_args())

    def test_exact_float64_roundtrip_and_readonly_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"stem-frozen-head.json"
            receipt = self.make(path)
            loaded = load_checkpoint(path, **{k: fixture_args()[k] for k in (
                "source_panel_digest", "model_revision", "pipeline_digest", "scope_id", "purpose_id", "generation", "authority_epoch")})
            self.assertEqual(receipt, loaded["receipt"])
            self.assertTrue(receipt["trained_weights_exact_float64_reloaded"])
            self.assertFalse(receipt["historical_20261014_head_byte_identity_claimed"])
            self.assertEqual(receipt["production_promotion"], "DENY_ALL")
            train = fake_cell(0.002)
            sample = np.random.default_rng(1).normal(size=(3, 256))
            np.testing.assert_array_equal(loaded["trained"].predict(sample), train.predict(sample))
            self.assertEqual(loaded["trained"].export_q24(), train.export_q24())
            with self.assertRaises(CheckpointError):
                loaded["trained"].learn(sample, np.ones(3))
            with self.assertRaises((ValueError, RuntimeError)):
                loaded["trained"]._cell.down[0, 0] = 3
            self.assertLessEqual(path.stat().st_size, 180_000)

    def test_forged_meta_or_tensor_digests_are_rejected(self):
        for issue in ("model", "source", "steps", "trained_float", "q24", "promotion", "frozen"):
            with self.subTest(issue=issue), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp)/"stem-frozen-head.json"
                self.make(path)
                data = json.loads(path.read_bytes())
                payload = data["payload"]
                if issue == "model": payload["model_revision"] = "f"*40
                if issue == "source": payload["source_panel_digest"] = "e"*64
                if issue == "steps": payload["steps"] = 0
                if issue == "trained_float": payload["trained"]["arrays"]["down"][0] = "0x1.0p+1"
                if issue == "q24": payload["trained"]["q24_candidate_digest"] = "e"*64
                if issue == "promotion": payload["production_promotion"] = "ALLOW"
                if issue == "frozen": payload["frozen"]["cell_id"] = "other.cell"
                data["payload_sha256"] = _sha(_canonical(payload))
                path.write_bytes(_canonical(data))
                with self.assertRaises(CheckpointError):
                    load_checkpoint(path, **{k: fixture_args()[k] for k in (
                        "source_panel_digest", "model_revision", "pipeline_digest", "scope_id", "purpose_id", "generation", "authority_epoch")})

    def test_checkpoint_is_not_overwritten_and_partial_bytes_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"stem-frozen-head.json"
            self.make(path)
            with self.assertRaises(CheckpointError):
                self.make(path)
            original = path.read_bytes()
            path.write_bytes(original[:-9])
            with self.assertRaises(CheckpointError):
                load_checkpoint(path, **{k: fixture_args()[k] for k in (
                    "source_panel_digest", "model_revision", "pipeline_digest", "scope_id", "purpose_id", "generation", "authority_epoch")})

    def test_authority_epoch_change_refuses_stale_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "stem-frozen-head.json"
            self.make(path)
            arguments = {k: fixture_args()[k] for k in (
                "source_panel_digest", "model_revision", "pipeline_digest",
                "scope_id", "purpose_id", "generation", "authority_epoch")}
            arguments["authority_epoch"] += 1
            with self.assertRaisesRegex(CheckpointError, "identity or permission"):
                load_checkpoint(path, **arguments)

    def test_frozen_and_trained_must_have_same_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            changed = fake_cell(0.002)
            changed.encoder_digest = "d"*64
            with self.assertRaises(CheckpointError):
                seal_checkpoint(Path(tmp)/"bad.json", fake_cell(), changed, **fixture_args())
            self.assertFalse((Path(tmp)/"bad.json").exists())

    def test_float_encoding_preserves_sub_q24_precision(self):
        with tempfile.TemporaryDirectory() as tmp:
            frozen, trained = fake_cell(), fake_cell(1e-9)
            # This tiny change can disappear in Q24, but float64 hex must persist.
            frozen.prediction_bias = 0.1111111111
            trained.prediction_bias = 0.2222222223
            path = Path(tmp)/"exact.json"
            self.assertTrue(seal_checkpoint(path, frozen, trained, **fixture_args()))
            obj = json.loads(path.read_bytes())["payload"]
            self.assertEqual(obj["frozen"]["scalars"]["prediction_bias"], (0.1111111111).hex())
            self.assertEqual(obj["trained"]["scalars"]["prediction_bias"], (0.2222222223).hex())


if __name__ == "__main__":
    unittest.main()
