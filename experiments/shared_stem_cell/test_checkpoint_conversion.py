"""Actual restricted Torch subprocess conversions of tiny test-only checkpoints."""
import os
import sys
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import torch
from safetensors.torch import load_file, save_file

from experiments.shared_stem_cell import checkpoint_conversion as c
from experiments.shared_stem_cell import execution as e


class ConversionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source.bin"
        self.output = self.root / "conversion"

    def tearDown(self):
        self.temp.cleanup()

    def execute(self, state):
        torch.save(state, self.source)
        return c.convert(self.source, c.digest_file(self.source), self.output, accepted=True)

    def test_real_conversion_tied_and_scalar(self):
        weight = torch.arange(8.).reshape(2, 4)
        state = {"weight": weight, "tied": weight, "scalar": torch.tensor(0.5),
                 "bf16": torch.tensor([0.125], dtype=torch.bfloat16)}
        report = self.execute(state)
        actual = load_file(self.output / "model.safetensors")
        self.assertEqual(set(actual), set(state))
        for key in state:
            self.assertTrue(torch.equal(actual[key], state[key]))
        self.assertEqual(report["tensor_count"], 4)
        self.assertFalse(report["hostile_code_sandbox"])
        self.assertFalse(report["production_accepted"])
        self.assertEqual(report["source_sha256"], c.digest_file(self.source))

    def test_explicit_acceptance_required(self):
        torch.save({"x": torch.ones(1)}, self.source)
        with self.assertRaisesRegex(ValueError, "acceptance"):
            c.convert(self.source, c.digest_file(self.source), self.output)
        self.assertFalse(self.output.exists())

    def test_source_digest_required(self):
        torch.save({"x": torch.ones(1)}, self.source)
        with self.assertRaises(ValueError):
            c.convert(self.source, "0" * 64, self.output, accepted=True)
        self.assertFalse(self.output.exists())

    def test_nested_checkpoint_rejected(self):
        with self.assertRaisesRegex(ValueError, "worker failed"):
            self.execute({"state_dict": {"x": torch.ones(1)}})
        self.assertFalse((self.output / "conversion.json").exists())
        self.assertTrue((self.output / "failure.json").exists())

    def test_nonfinite_tensor_rejected(self):
        with self.assertRaisesRegex(ValueError, "worker failed"):
            self.execute({"x": torch.tensor([float("nan")])})
        self.assertFalse((self.output / "model.safetensors").exists())

    def test_custom_python_object_never_allowlisted(self):
        with self.assertRaisesRegex(ValueError, "worker failed"):
            self.execute({"x": SimpleNamespace(value=1)})
        self.assertFalse((self.output / "conversion.json").exists())
        self.assertIn("Weights only load failed", (self.output / "worker.log").read_text())

    def test_environment_cannot_disable_restricted_load(self):
        with patch.dict(os.environ, {"TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD": "1"}):
            report = self.execute({"x": torch.ones(1)})
        self.assertTrue(report["weights_only"])

    def test_output_never_overwritten(self):
        self.execute({"x": torch.ones(1)})
        before = c.digest_file(self.output / "model.safetensors")
        with self.assertRaises(FileExistsError):
            c.convert(self.source, c.digest_file(self.source), self.output, accepted=True)
        self.assertEqual(before, c.digest_file(self.output / "model.safetensors"))

    def test_scalar_hash_uses_original_shape(self):
        self.assertNotEqual(e.tensor_digest(torch.tensor(1.)), e.tensor_digest(torch.tensor([1.])))

    def test_materialized_missing_load_info_rejected(self):
        with self.assertRaises(e.InputError):
            e.verify_materialized(torch.nn.Linear(2, 2), {}, self.root, {"files": {}})

    def test_materialized_transposed_storage_not_a_tied_alias(self):
        class Model(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.weight = torch.nn.Parameter(torch.arange(4.).reshape(2, 2))
                self.transposed = torch.nn.Parameter(self.weight.T)
        model = Model()
        save_file({"weight": model.weight.detach().contiguous()}, str(self.root / "model.safetensors"))
        info = {k: [] for k in ("missing_keys", "unexpected_keys", "mismatched_keys", "error_msgs")}
        with self.assertRaisesRegex(e.InputError, "unverified"):
            e.verify_materialized(model, info, self.root, {"files": {"model.safetensors": "unused"}})


class PublicSourceTests(unittest.TestCase):
    def test_bin_acquisition_requires_acceptance_and_keeps_original_separate(self):
        from experiments.shared_stem_cell.public_smoke import stage_model
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            snapshot = root / "snapshot"
            snapshot.mkdir()
            torch.save({"x": torch.ones(2)}, snapshot / "pytorch_model.bin")
            (snapshot / "config.json").write_text("{}")
            expected = c.digest_file(snapshot / "pytorch_model.bin")
            info = SimpleNamespace(sha="a" * 40, siblings=[
                SimpleNamespace(rfilename=p.name, size=p.stat().st_size,
                    lfs={"sha256": c.digest_file(p)}) for p in snapshot.iterdir()])
            hub = SimpleNamespace(HfApi=lambda: SimpleNamespace(model_info=lambda *a, **kw: info),
                                  snapshot_download=lambda *a, **kw: str(snapshot))
            denied = root / "denied"
            denied.mkdir()
            accepted = root / "accepted"
            accepted.mkdir()
            previous = sys.modules.get("huggingface_hub")
            sys.modules["huggingface_hub"] = hub
            try:
                with self.assertRaisesRegex(ValueError, "explicit separate"):
                    stage_model(denied, "public/test-only", "a" * 40, kind="encoder")
                result = stage_model(accepted, "public/test-only", "a" * 40,
                                     kind="encoder", allow_conversion=True)
            finally:
                if previous is None:
                    sys.modules.pop("huggingface_hub", None)
                else:
                    sys.modules["huggingface_hub"] = previous
            self.assertEqual(result["conversion"]["source_sha256"], expected)
            self.assertFalse((accepted / "model/pytorch_model.bin").exists())
            self.assertTrue((accepted / "source-weights.bin").is_file())
            self.assertEqual(set(result["files"]), {"config.json", "model.safetensors"})
            e.verify_snapshot(accepted / "model", result)


if __name__ == "__main__":
    unittest.main()
