"""Worker lifecycle/integrity regressions; the fake backbone is not model evidence."""
import hashlib
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import torch
from safetensors.torch import save_file

WORKER = Path(__file__).resolve().parents[2] / "hepta-infer-worker-host/python"
sys.path.insert(0, str(WORKER))
import decision_cell_encoder as encoder
import decision_cell_tensors as tensors
from test_tensor_bundle import canonical, fixture_manifest


def tokenize(texts, **kwargs):
    lengths = [len(text.split()) + 2 for text in texts]
    ids = torch.zeros(len(texts), max(lengths), dtype=torch.long)
    for i, (text, count) in enumerate(zip(texts, lengths)):
        ids[i, :count] = 1 + sum(text.encode()) % 79
    return {"input_ids": ids, "attention_mask": (ids != 0).long()}


def backbone(**values):
    return SimpleNamespace(last_hidden_state=values["input_ids"].float().unsqueeze(-1).repeat(1, 1, 8) / 80)


class FrozenEncoderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / "base"
        self.base.mkdir()
        files = []
        for name in sorted(encoder.BASE_FILES):
            data = ("fixture-only-" + name).encode()
            (self.base / name).write_bytes(data)
            files.append({"path": name, "bytes": len(data),
                          "sha256": hashlib.sha256(data).hexdigest()})
        self.snapshot = hashlib.sha256(encoder._canonical(files)).hexdigest()
        model = tensors.TypedHeads(8, 4).eval()
        self.weights = self.root / "heads.safetensors"
        save_file(model.state_dict(), self.weights)
        calibration = {"temperatures": {key: 0.5 for key in
                       ("action", "target", "disposition", "postcondition", "ood")},
                       "minimum_confidence": 0.2, "maximum_ood_probability": 0.7}
        self.manifest = fixture_manifest(model, calibration, self.weights.read_bytes())
        self.manifest["base_model"] = {"repo": encoder.BASE_REPO,
            "revision": encoder.BASE_REVISION, "trust_remote_code": False,
            "files": files, "snapshot_digest": self.snapshot}
        self.manifest_path = self.root / "manifest.json"
        self.texts = ("choose an observed target",)
        self.targets = (("document A", "window B", "button C", "item D"),)

    def load(self):
        raw = canonical(self.manifest)
        self.manifest_path.write_bytes(raw)
        model = encoder.FrozenMdebertaDecisionCellV2(
            model_path=self.base, manifest_path=self.manifest_path,
            manifest_sha256=hashlib.sha256(raw).hexdigest(), weights_path=self.weights,
            weights_sha256=self.manifest["weights_sha256"],
            expected_base_snapshot=self.snapshot,
            expected_runtime_profile=self.manifest["runtime_profile"])
        self.addCleanup(model.close)
        return model

    def observe(self, model):
        return model.observe(self.texts, self.targets, deadline_ns=time.monotonic_ns() + 10**10)

    @patch.object(encoder, "_load_backbone", return_value=(tokenize, backbone))
    def test_reuses_one_load_and_returns_actual_head_tensors(self, loader):
        model = self.load()
        first, second = self.observe(model), self.observe(model)
        self.assertEqual(loader.call_count, 1)
        self.assertEqual(model.forward_passes, 4)
        self.assertEqual(first["base_forward_passes"], 2)
        self.assertEqual(first["input_sha256"], second["input_sha256"])
        self.assertFalse(first["external_effect"])
        for key in first["scores"]:
            self.assertTrue(torch.equal(first["scores"][key], second["scores"][key]))
        private = Path(model._private.name)
        self.assertNotEqual((private / "config.json").stat().st_ino,
                            (self.base / "config.json").stat().st_ino)

    @patch.object(encoder, "_load_backbone", return_value=(tokenize, backbone))
    def test_private_snapshot_survives_original_mutation_and_closes(self, loader):
        model = self.load()
        private = Path(model._private.name)
        original = (private / "config.json").read_bytes()
        (self.base / "config.json").write_bytes(b"replacement")
        self.assertEqual((private / "config.json").read_bytes(), original)
        self.observe(model)
        model.close()
        self.assertFalse(private.exists())
        with self.assertRaisesRegex(RuntimeError, "closed"):
            self.observe(model)

    @patch.object(encoder, "_load_backbone")
    def test_corrupt_source_rejected_before_model_code(self, loader):
        path = self.base / "config.json"
        path.write_bytes(b"x" * path.stat().st_size)
        with self.assertRaisesRegex(ValueError, "content mismatch"):
            self.load()
        loader.assert_not_called()

    @patch.object(encoder, "_load_backbone")
    def test_source_symlink_rejected(self, loader):
        path = self.base / "config.json"
        copied = self.root / "elsewhere"
        path.rename(copied)
        path.symlink_to(copied)
        with self.assertRaises((OSError, ValueError)):
            self.load()
        loader.assert_not_called()

    @patch.object(encoder, "_load_backbone")
    def test_unsupported_base_and_remote_code_reject(self, loader):
        for key, value in (("revision", "0" * 40), ("trust_remote_code", True)):
            original = self.manifest["base_model"][key]
            self.manifest["base_model"][key] = value
            with self.assertRaises(ValueError):
                self.load()
            self.manifest["base_model"][key] = original
        loader.assert_not_called()

    @patch.object(encoder, "_load_backbone", return_value=(tokenize, backbone))
    def test_rejects_truncation_instead_of_losing_target(self, loader):
        model = self.load()
        with self.assertRaisesRegex(ValueError, "token budget"):
            model.observe(("word " * 193,), self.targets,
                          deadline_ns=time.monotonic_ns() + 10**10)
        self.assertEqual(model.forward_passes, 0)

    @patch.object(encoder, "_load_backbone", return_value=(tokenize, backbone))
    def test_rejects_expired_work_before_forward(self, loader):
        model = self.load()
        with self.assertRaises(TimeoutError):
            model.observe(self.texts, self.targets, deadline_ns=0)
        self.assertEqual(model.forward_passes, 0)
        for value in (True, 1.2):
            with self.assertRaises(TimeoutError):
                model.observe(self.texts, self.targets, deadline_ns=value)
