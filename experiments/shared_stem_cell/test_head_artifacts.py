"""Actual optimization, safetensors export and fresh-process CPU replay.

Features below are synthetic. A working candidate file is not a signed product
artifact or a demonstration of pretrained-model or independent future efficacy.
"""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import torch
from safetensors.torch import load, save

from experiments.shared_stem_cell import execution as e
from experiments.shared_stem_cell import head_artifacts as a


class HeadArtifactTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        torch.manual_seed(17)
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / "head"
        self.binding = {"scope": "test-scope", "logical_cell": "cell-7", "generation": 1,
                        **{k: e.sha(k.encode()) for k in a.BINDING_KEYS if k.endswith("sha256")}}
        self.x = torch.randn(16, 8)
        self.y = (self.x[:, 0] > 0).long()
        self.initial = e.Head(8, 2, "gated", 4).eval()
        self.model, self.cost = e.fit(self.initial, self.x, self.y, steps=4)

    def tearDown(self):
        self.temp.cleanup()

    def export(self, model=None):
        return a.export_head(self.path, self.model if model is None else model, self.binding)

    def mutate_manifest(self, change):
        path = self.path / "manifest.json"
        manifest = e.decode(path.read_bytes())
        change(manifest)
        raw = e.canonical(manifest)
        path.write_bytes(raw)
        return e.sha(raw)

    def test_all_existing_heads_exact_roundtrip(self):
        for kind in sorted(a.KINDS):
            with self.subTest(kind=kind):
                model, _ = e.fit(e.Head(8, 2, kind, 4), self.x, self.y, steps=3)
                path = self.root / kind
                receipt = a.export_head(path, model, self.binding)
                restored = a.load_head(path, receipt["manifest_sha256"], self.binding)
                self.assertEqual(e.parameters(model), e.parameters(restored))
                self.assertTrue(torch.equal(model(self.x), restored(self.x)))
                self.assertFalse(any(p.requires_grad for p in restored.parameters()))
                self.assertFalse(receipt["production_accepted"])

    def test_actual_fresh_process_replay(self):
        receipt = self.export()
        e.write_once(self.root / "binding.json", self.binding)
        raw = save({"x": self.x, "logits": self.model(self.x).detach().contiguous()})
        (self.root / "probe.safetensors").write_bytes(raw)
        code = """
from pathlib import Path
import json, os, sys, torch
from safetensors.torch import load_file
from experiments.shared_stem_cell.head_artifacts import load_head
from experiments.shared_stem_cell.execution import parameters, tensor_digest, write_once
torch.set_num_threads(1)
root=Path(sys.argv[1])
model=load_head(root/'head',sys.argv[2],json.loads((root/'binding.json').read_bytes()))
probe=load_file(root/'probe.safetensors')
mapped=model(probe['x'])
# Match the owner's allocated feature materialization, not safetensors mmap alignment.
actual=model(probe['x'].clone().contiguous())
assert torch.equal(actual,probe['logits'])
write_once(root/'replay.json',{'pid':os.getpid(),'logits_sha256':tensor_digest(actual),
                            'parameters':parameters(model),
                            'mapped_input_max_abs_difference':float((mapped-probe['logits']).abs().max()),
                            'owned_float32_input_logits_exact':True,'production_accepted':False})
"""
        result = subprocess.run([sys.executable, "-c", code, str(self.root), receipt["manifest_sha256"]],
                                capture_output=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, (result.stdout + result.stderr).decode())
        report = json.loads((self.root / "replay.json").read_bytes())
        self.assertNotEqual(report["pid"], os.getpid())
        self.assertEqual(report["logits_sha256"], e.tensor_digest(self.model(self.x)))

    def test_candidate_training_does_not_mutate_saved_or_selected_head(self):
        receipt = self.export()
        restored = a.load_head(self.path, receipt["manifest_sha256"], self.binding)
        selected_hash = e.parameters(restored)["sha256"]
        trainable = copy.deepcopy(restored).requires_grad_(True)
        candidate, cost = e.fit(trainable, self.x, self.y, steps=4)
        self.assertNotEqual(e.parameters(candidate)["sha256"], selected_hash)
        self.assertEqual(e.parameters(restored)["sha256"], selected_hash)
        again = a.load_head(self.path, receipt["manifest_sha256"], self.binding)
        self.assertEqual(e.parameters(again)["sha256"], selected_hash)
        self.assertEqual(cost["steps"], 4)
        self.assertFalse(e.decode((self.path / "manifest.json").read_bytes())["optimizer_state_included"])

    def test_stale_scope_encoder_dataset_feature_generation_rejected(self):
        receipt = self.export()
        for key in sorted(a.BINDING_KEYS):
            binding = dict(self.binding)
            binding[key] = 2 if key == "generation" else ("0" * 64 if key.endswith("sha256") else "other")
            with self.subTest(key=key), self.assertRaises(e.InputError):
                a.load_head(self.path, receipt["manifest_sha256"], binding)

    def test_external_manifest_hash_required(self):
        self.export()
        with self.assertRaises(e.InputError):
            a.load_head(self.path, "0" * 64, self.binding)

    def test_corrupt_tensor_bytes_rejected(self):
        receipt = self.export()
        path = self.path / "weights.safetensors"
        raw = bytearray(path.read_bytes()); raw[-1] ^= 1; path.write_bytes(raw)
        with self.assertRaises(e.InputError):
            a.load_head(self.path, receipt["manifest_sha256"], self.binding)

    def test_rehashed_wrong_tensor_shapes_rejected(self):
        self.export()
        path = self.path / "weights.safetensors"
        tensors = load(path.read_bytes()); tensors["base.weight"] = tensors["base.weight"].T.contiguous()
        raw = save(tensors); path.write_bytes(raw)
        h = self.mutate_manifest(lambda m: m.update(weights_sha256=e.sha(raw), weights_bytes=len(raw)))
        with self.assertRaises(e.InputError):
            a.load_head(self.path, h, self.binding)

    def test_rehashed_nonfinite_tensor_rejected(self):
        self.export()
        path = self.path / "weights.safetensors"
        tensors = load(path.read_bytes()); tensors["base.weight"][0, 0] = float("nan")
        raw = save(tensors); path.write_bytes(raw)
        h = self.mutate_manifest(lambda m: m.update(weights_sha256=e.sha(raw), weights_bytes=len(raw)))
        with self.assertRaises(e.InputError):
            a.load_head(self.path, h, self.binding)

    def test_no_arbitrary_type_or_allocation(self):
        self.export()
        for architecture in ({"kind": "import.os", "width": 8, "classes": 2, "rank": 4},
                             {"kind": "gated", "width": 100000000, "classes": 2, "rank": 4}):
            h = self.mutate_manifest(lambda m: m.update(architecture=architecture))
            with self.assertRaises(e.InputError):
                a.load_head(self.path, h, self.binding)

    def test_no_production_or_optimizer_claim_from_artifact(self):
        self.export()
        for key in ("production_accepted", "optimizer_state_included"):
            h = self.mutate_manifest(lambda m: m.update({key: True}))
            with self.assertRaises(e.InputError):
                a.load_head(self.path, h, self.binding)

    def test_unknown_partial_directory_rejected(self):
        receipt = self.export()
        (self.path / "manifest.json").unlink()
        with self.assertRaises(e.InputError):
            a.load_head(self.path, receipt["manifest_sha256"], self.binding)

    def test_overwrite_and_symlink_rejected(self):
        receipt = self.export()
        with self.assertRaises(FileExistsError):
            self.export()
        alias = self.root / "alias"; alias.symlink_to(self.path, target_is_directory=True)
        with self.assertRaises(e.InputError):
            a.load_head(alias, receipt["manifest_sha256"], self.binding)

    def test_reopen_preserves_training_rng(self):
        receipt = self.export()
        before = torch.get_rng_state().clone()
        a.load_head(self.path, receipt["manifest_sha256"], self.binding)
        self.assertTrue(torch.equal(before, torch.get_rng_state()))

    def test_existing_head_trial_exports_actual_models(self):
        cases = tuple(e.Case(str(i), str(i), "train" if i < 8 else "holdout", i,
                            i % 2, "test-scope", f"case {i}") for i in range(16))
        labels = {c.case_id: int(self.y[i]) for i, c in enumerate(cases) if c.split == "train"}
        binding = {k: v for k, v in self.binding.items() if k not in {"logical_cell", "training_lineage_sha256"}}
        predictions, costs = e.head_trial(self.x, cases, labels, classes=2, kind="gated", steps=4,
                                         seed=17, artifact_dir=self.root / "trial", artifact_binding=binding)
        for cost in costs:
            cell = cost["cell"]; entry = cost["offline_head_artifacts"]["learned"]
            model = a.load_head(self.root / "trial" / entry["relative_path"], entry["manifest_sha256"], entry["binding"])
            ids = [i for i, c in enumerate(cases) if c.cell == cell and c.split == "holdout"]
            actual = model(self.x[ids]).softmax(-1).tolist()
            self.assertEqual(actual, [p["probabilities"] for p in predictions if p["cell"] == cell])
            self.assertTrue(entry["reload_logits_exact"])

    def test_export_scope_preflight_precedes_training(self):
        cases = (e.Case("0", "g", "train", None, 0, "foreign", "input"),)
        binding = {k: v for k, v in self.binding.items() if k not in {"logical_cell", "training_lineage_sha256"}}
        with patch.object(e, "fit") as fitter, self.assertRaises(e.InputError):
            e.head_trial(self.x[:1], cases, {"0": 0}, classes=2, kind="linear", steps=1,
                         seed=17, artifact_dir=self.root / "trial", artifact_binding=binding)
        fitter.assert_not_called()

    def test_non_head_and_nonfinite_export_rejected(self):
        for model in (torch.nn.Linear(8, 2), copy.deepcopy(self.model)):
            if type(model) is e.Head:
                with torch.no_grad():
                    model.base.weight[0, 0] = float("inf")
            with self.assertRaises(e.InputError):
                self.export(model)
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
