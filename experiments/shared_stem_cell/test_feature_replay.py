"""Real file/Head replay and poisoned-archive rejection; fixtures are NOT pretrained."""
from copy import deepcopy
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import torch
from safetensors.torch import load, save

from experiments.shared_stem_cell import execution as e
from experiments.shared_stem_cell import feature_replay as f


class FeatureReplayTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        torch.manual_seed(91)
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.x = torch.randn(12, 8)
        self.cases = tuple(e.Case(str(i), str(i), "train" if i < 6 else
            "calibration" if i < 8 else "holdout", None, i % 2, "scope", f"sample:{i}") for i in range(12))
        self.config = {"schema": "hepta.shared-stem-execution.v1", "model": {"path": "absent-model"},
                       "dataset": {"path": "data.jsonl", "sha256": "b"*64}, "classes": 3, "cells": 2,
                       "steps": 4, "seed": 17, "export_frozen_features": True}
        self.source = "c"*64
        self.directory = self.root / "features"

    def tearDown(self):
        self.temp.cleanup()

    def export(self):
        return f.export_features(self.directory, self.x, self.cases, self.config,
                                 producer_source_sha256=self.source, simulated=True)

    def reopen(self, digest):
        return f.load_features(self.directory, digest, self.cases, self.config, producer_source_sha256=self.source)

    def alter(self, *, update_manifest=None, update_tensors=None):
        m = e.decode((self.directory / "manifest.json").read_bytes())
        if update_tensors:
            tensors = load((self.directory / "features.safetensors").read_bytes())
            update_tensors(tensors)
            raw = save(tensors)
            (self.directory / "features.safetensors").write_bytes(raw)
            m.update(file_sha256=e.sha(raw), file_bytes=len(raw))
            if "features" in tensors:
                m["tensor_sha256"] = e.tensor_digest(tensors["features"])
        if update_manifest:
            update_manifest(m)
        raw = e.canonical(m)
        (self.directory / "manifest.json").write_bytes(raw)
        return e.sha(raw)

    def producer(self):
        rows = [{"case_id": c.case_id, "group": c.group, "split": c.split, "observed_at": None,
                 "cell": c.cell, "scope": c.scope, "text": c.text, "label": int(c.case_id) % 3} for c in self.cases]
        raw = b"".join(e.canonical(r) for r in rows)
        (self.root / "data.jsonl").write_bytes(raw)
        self.config["dataset"]["sha256"] = e.sha(raw)
        e.write_once(self.root / "manifest.json", self.config)
        outer = self
        class Encoder:
            simulated = True
            identity = e.sha(e.canonical(outer.config["model"]))
            calls = 0
            def encode(self, texts):
                Encoder.calls += 1
                return torch.stack([outer.x[int(t.split(":")[1])] for t in texts])
            def close(self):
                pass
        with patch.object(e, "LocalEncoder", return_value=Encoder()):
            report = e.run(self.root / "manifest.json", self.root / "producer")
        self.assertEqual(Encoder.calls, 2)
        return report, e.sha((self.root / "producer/report.json").read_bytes())

    def test_exact_tensor_roundtrip_without_raw_text_or_labels(self):
        before = torch.get_rng_state().clone()
        receipt = self.export(); actual, manifest = self.reopen(receipt["manifest_sha256"])
        self.assertTrue(torch.equal(actual, self.x))
        self.assertTrue(torch.equal(before, torch.get_rng_state()))
        self.assertNotIn("label", manifest["rows"][0]); self.assertNotIn("text", manifest["rows"][0])
        self.assertTrue(manifest["simulated_encoder"])
        self.assertFalse(manifest["production_accepted"])
        actual[0, 0] += 5
        self.assertTrue(torch.equal(self.reopen(receipt["manifest_sha256"])[0], self.x))

    def test_feature_snapshot_owns_bytes_after_source_mutation(self):
        receipt = self.export(); expected = self.x.clone(); self.x.add_(1)
        self.assertTrue(torch.equal(self.reopen(receipt["manifest_sha256"])[0], expected))

    def test_wrong_external_digest_rejects_before_deserialization(self):
        self.export()
        with patch.object(f, "load") as decoder, self.assertRaises(e.InputError):
            self.reopen("d"*64)
        decoder.assert_not_called()

    def test_scope_fold_cell_order_and_input_bindings_cannot_drift(self):
        from dataclasses import replace
        receipt = self.export(); original = self.cases
        for change in ({"scope":"another"}, {"cell":3}, {"split":"holdout"}, {"text":"changed"}):
            self.cases = (replace(original[0], **change), *original[1:])
            with self.assertRaises(e.InputError): self.reopen(receipt["manifest_sha256"])
        self.cases = tuple(reversed(original))
        with self.assertRaises(e.InputError): self.reopen(receipt["manifest_sha256"])

    def test_stem_dataset_profile_and_producer_plan_are_bound(self):
        receipt = self.export(); original = deepcopy(self.config)
        for key, value in (("model", {"path":"other"}), ("dataset", {"path":"data.jsonl","sha256":"a"*64}),
                           ("maximum_tokens", 128), ("seed", 23)):
            self.config = {**deepcopy(original), key:value}
            with self.assertRaises(e.InputError): self.reopen(receipt["manifest_sha256"])
        self.config = original; self.source = "d"*64
        with self.assertRaises(e.InputError): self.reopen(receipt["manifest_sha256"])

    def test_invalid_input_precedes_any_file_creation(self):
        for x in (self.x.double(), self.x.unsqueeze(0), torch.full_like(self.x, float("nan"))):
            with self.assertRaises(e.InputError):
                f.export_features(self.directory, x, self.cases, self.config,
                                   producer_source_sha256=self.source, simulated=True)
            self.assertFalse(self.directory.exists())
        with patch.object(f, "MAX_TENSOR", 4):
            with self.assertRaises(e.InputError): self.export()
        self.assertFalse(self.directory.exists())

    def test_incomplete_extra_linked_and_overwritten_snapshots_reject(self):
        receipt = self.export()
        with self.assertRaises(e.InputError): self.export()
        alias = self.root / "alias"; alias.symlink_to(self.directory, target_is_directory=True)
        with self.assertRaises(e.InputError):
            f.load_features(alias, receipt["manifest_sha256"], self.cases, self.config, producer_source_sha256=self.source)
        (self.directory / "extra").write_text("x")
        with self.assertRaises(e.InputError): self.reopen(receipt["manifest_sha256"])
        (self.directory / "extra").unlink(); (self.directory / "features.safetensors").unlink()
        with self.assertRaises(e.InputError): self.reopen(receipt["manifest_sha256"])

    def test_rehashed_nan_wrong_dtype_shape_and_extra_tensors_reject(self):
        mutations = (lambda t: t["features"].fill_(float("nan")),
            lambda t: t.update(features=t["features"].double()),
            lambda t: t.update(features=t["features"].T.contiguous()),
            lambda t: t.update(labels=torch.zeros(12, dtype=torch.long)))
        for i, mutate in enumerate(mutations):
            self.directory = self.root / str(i); self.export()
            digest = self.alter(update_tensors=mutate)
            with self.assertRaises(e.InputError): self.reopen(digest)

    def test_rehashed_shape_budget_rejects_before_decoder(self):
        self.export()
        digest = self.alter(update_manifest=lambda m: m.update(shape=[16384, 8192]))
        with patch.object(f, "load") as decoder, self.assertRaises(e.InputError): self.reopen(digest)
        decoder.assert_not_called()

    def test_actual_producer_then_scalar_and_grouped_replay_without_encoder(self):
        source, digest = self.producer()
        original = (self.root / "producer/frozen-features/features.safetensors").read_bytes()
        for backend in ("scalar", "grouped"):
            with patch.object(e, "LocalEncoder", side_effect=AssertionError("Encoder must not load")):
                report = f.replay(self.root/"manifest.json", self.root/"producer", digest,
                                  self.root/backend, fitting_backend=backend)
            self.assertEqual(report["encoder_forward_calls"], 0)
            for actual, expected in zip(report["scores"], source["scores"]):
                self.assertEqual({k:v for k,v in actual.items() if k != "brier"},
                                 {k:v for k,v in expected.items() if k != "brier"})
                self.assertAlmostEqual(actual["brier"], expected["brier"], delta=f.ATOL)
            self.assertTrue(all(r["within_tolerance"] and r["exact_minibatch_streams"] for r in report["comparison"]))
            self.assertTrue(report["source_simulated_encoder"])
        self.assertEqual(original, (self.root / "producer/frozen-features/features.safetensors").read_bytes())

    def test_new_process_replays_with_transformers_import_forbidden(self):
        _, digest = self.producer()
        code = '''import sys, importlib.abc
class Block(importlib.abc.MetaPathFinder):
 def find_spec(self, fullname, *args):
  if fullname.split('.')[0] in {'transformers','tokenizers','huggingface_hub'}:
   raise AssertionError('replay imported a model dependency')
sys.meta_path.insert(0, Block())
from pathlib import Path
import torch
from experiments.shared_stem_cell.feature_replay import replay
torch.set_num_threads(1)
root=Path(sys.argv[1])
replay(root/'manifest.json',root/'producer',sys.argv[2],root/'fresh')
'''
        result = subprocess.run([sys.executable, "-c", code, str(self.root), digest], capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        report = json.loads((self.root/"fresh/report.json").read_text())
        self.assertFalse(report["encoder_loaded"])

    def test_invalid_export_flag_rejected_before_loading(self):
        self.config["export_frozen_features"] = 1
        e.write_once(self.root/"manifest.json", self.config)
        with patch.object(e, "LocalEncoder") as encoder, self.assertRaises(e.InputError):
            e.run(self.root/"manifest.json", self.root/"producer")
        encoder.assert_not_called()

    def test_wrong_report_or_changed_dataset_rejects_before_fit(self):
        _, digest = self.producer()
        with patch.object(e, "head_trial") as fit, self.assertRaises(e.InputError):
            f.replay(self.root/"manifest.json", self.root/"producer", "0"*64, self.root/"bad")
        fit.assert_not_called()
        (self.root/"data.jsonl").write_text('{}\n')
        with patch.object(e, "head_trial") as fit, self.assertRaises(e.InputError):
            f.replay(self.root/"manifest.json", self.root/"producer", digest, self.root/"changed")
        fit.assert_not_called()

    def test_mismatch_is_retained_and_fails_not_silently_repaired(self):
        source, _ = self.producer()
        p = self.root / "producer/predictions.json"; rows = e.decode(p.read_bytes())
        for r in rows["predictions"]: r["probabilities"] = [1., 0., 0.]
        p.write_bytes(e.canonical(rows)); source["predictions_sha256"] = e.sha(p.read_bytes())
        r = self.root / "producer/report.json"; r.write_bytes(e.canonical(source))
        with self.assertRaisesRegex(e.InputError, "mismatch retained"):
            f.replay(self.root/"manifest.json", self.root/"producer", e.sha(r.read_bytes()), self.root/"mismatch")
        self.assertTrue((self.root/"mismatch/predictions.json").is_file())
        self.assertTrue((self.root/"mismatch/report.json").is_file())
        self.assertTrue((self.root/"mismatch/failure.json").is_file())


if __name__ == "__main__":
    unittest.main()
