"""Hermetic model-stub test of OPTIONAL teacher forward -> feature shard wiring.

No pretrained teacher checkpoint or capability is loaded. This test ensures
the caller's *already-computed* teacher vector is actually exportable.
"""
from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
import hashlib
import pathlib
import sys
import tempfile
import types
import unittest
from unittest import mock

try:
    import torch
except ImportError:
    torch = None

if torch is not None:
    sys.path.insert(0, str(pathlib.Path(__file__).parent))
    import teacher_forward
    from feature_shard import read_shard


@unittest.skipUnless(torch is not None, "optional Torch synthetic export test")
class TeacherFeatureExportTests(unittest.TestCase):
    def test_hermetic_model_stub_features_are_saved_and_bound(self):
        class FakeModel(torch.nn.Module):
            def forward(self, **_kwargs):
                values = torch.zeros(1, 2, 768, dtype=torch.float32)
                values[0, 0, 0] = 3.
                values[0, 0, 1] = 4.
                values[0, 1, 0] = 3.
                values[0, 1, 1] = 4.
                return SimpleNamespace(last_hidden_state=values)

        class FakeProcessor:
            def apply_chat_template(self, _conversations, **_kwargs):
                return {"input_ids": torch.tensor([[7, 8]]),
                        "attention_mask": torch.tensor([[1, 1]])}

        fake_transformers = types.ModuleType("transformers")
        fake_transformers.AutoProcessor = SimpleNamespace(
            from_pretrained=lambda *a, **kw: FakeProcessor())
        fake_transformers.AutoModel = SimpleNamespace(
            from_pretrained=lambda *a, **kw: FakeModel())
        # Both aliases required at import time; neither executed here.
        fake_transformers.AutoModelForSeq2SeqLM = object()
        fake_transformers.AutoTokenizer = object()

        with tempfile.TemporaryDirectory() as tmp, ExitStack() as patches:
            patches.enter_context(mock.patch.dict(sys.modules, {
                "transformers": fake_transformers}))
            patches.enter_context(mock.patch.object(
                teacher_forward, "verify_snapshot", return_value={
                    "revision": "a" * 40, "inventory_sha256": "b" * 64}))
            patches.enter_context(mock.patch.object(
                teacher_forward, "validate_records",
                return_value=([[{"role": "user", "content": [
                    {"type": "text", "text": "hello"}]}]], "c" * 64)))
            path = pathlib.Path(tmp) / "export"
            result = teacher_forward.run_forward(
                candidate="embeddinggemma2_740m", snapshot=tmp,
                media_root=tmp, records=[{"text": "hello"}],
                revision="a" * 40,
                expected_inventory_sha256="b" * 64,
                operator_accepted_terms=True, device="cpu",
                truncate_dim=256, feature_output_dir=path,
            )
            values, manifest = read_shard(path)
            self.assertEqual(tuple(values.shape), (1, 256))
            self.assertAlmostEqual(float(values[0, 0]), 0.6, places=5)
            self.assertAlmostEqual(float(values[0, 1]), 0.8, places=5)
            self.assertEqual(
                hashlib.sha256(values.numpy().tobytes()).hexdigest(),
                result["feature_sha256"])
            self.assertEqual(result["feature_export"]["raw_feature_sha256"],
                             result["feature_sha256"])
            self.assertEqual(manifest["candidate"], "embeddinggemma2_740m")
            self.assertEqual(manifest["ordered_source_manifest_sha256"],
                             "c" * 64)
            self.assertEqual(result["owner_model_forward_hook_calls"], 1)
            self.assertFalse(result["model_performance_qualified"])
            self.assertFalse(result["producer_attested_independently"])
            self.assertFalse(result["feature_export"]["production_activation_allowed"])


if __name__ == "__main__":
    unittest.main()
