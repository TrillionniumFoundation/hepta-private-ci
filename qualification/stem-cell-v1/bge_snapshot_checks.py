"""Synthetic snapshot translation tests; never publisher/model evidence."""
from copy import deepcopy
import hashlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import torch
from safetensors.torch import load, save

import bge_snapshot_canonicalization as conversion
from public_structural_stage import MODEL_FILES, stage


class Tiny(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.embeddings = torch.nn.Module()
        self.embeddings.register_buffer("position_ids", torch.arange(512).unsqueeze(0), persistent=False)
        self.embeddings.weight = torch.nn.Parameter(torch.ones(2, 3))

    def forward(self, **_):
        return types.SimpleNamespace(last_hidden_state=self.embeddings.weight[None, :, :])


class SnapshotChecks(unittest.TestCase):
    def setUp(self):
        self.model = Tiny()
        self.original = dict(self.model.state_dict(), **{conversion.BUFFER: self.model.get_buffer(conversion.BUFFER).clone()})

    def test_only_deterministic_buffer_removed_and_parameter_bits_unchanged(self):
        result = conversion.validated_parameters(self.model, self.original)
        self.assertEqual(set(result), {"embeddings.weight"})
        self.assertTrue(torch.equal(result["embeddings.weight"], self.original["embeddings.weight"]))
        self.assertNotEqual(result["embeddings.weight"].data_ptr(), self.original["embeddings.weight"].data_ptr())

    def test_unknown_extra_key_is_not_ignored(self):
        self.original["unexpected"] = torch.ones(1)
        with self.assertRaises(ValueError):
            conversion.validated_parameters(self.model, self.original)

    def test_missing_learned_key_rejected(self):
        del self.original["embeddings.weight"]
        with self.assertRaises(ValueError):
            conversion.validated_parameters(self.model, self.original)

    def test_absent_buffer_not_silently_identity_conversion(self):
        del self.original[conversion.BUFFER]
        with self.assertRaises(ValueError):
            conversion.validated_parameters(self.model, self.original)

    def test_buffer_value_dtype_and_shape_are_exact(self):
        for value in (torch.zeros(1, 512, dtype=torch.long), torch.arange(512).float()[None], torch.arange(512)):
            with self.subTest(shape=value.shape, dtype=value.dtype), self.assertRaises(ValueError):
                conversion.validated_parameters(self.model, dict(self.original, **{conversion.BUFFER: value}))

    def test_runtime_buffer_must_agree(self):
        self.model.embeddings.position_ids = torch.zeros(1, 512, dtype=torch.long)
        with self.assertRaises(ValueError):
            conversion.validated_parameters(self.model, self.original)

    def test_learned_tensor_must_not_change_or_cast(self):
        for value in (torch.zeros(2, 3), torch.ones(2, 3).half(), torch.ones(3, 2)):
            with self.subTest(shape=value.shape, dtype=value.dtype), self.assertRaises(ValueError):
                conversion.validated_parameters(self.model, dict(self.original, **{"embeddings.weight": value}))

    def test_persistent_or_learned_position_ids_cannot_be_dropped(self):
        self.model.embeddings._non_persistent_buffers_set.clear()
        with self.assertRaises(ValueError):
            conversion.validated_parameters(self.model, self.original)

    def test_source_loading_has_no_other_allowed_exception(self):
        info = {k: [] for k in ("missing_keys", "mismatched_keys", "unexpected_keys", "error_msgs")}
        conversion.verify_source_loading(info)
        conversion.verify_source_loading(dict(info, unexpected_keys=[conversion.BUFFER]))
        for changed in ({}, dict(info, missing_keys=["x"]), dict(info, unexpected_keys=["x"]),
                        dict(info, unexpected_keys=[conversion.BUFFER]*2), dict(info, error_msgs=["bad"])):
            with self.subTest(info=changed), self.assertRaises(ValueError):
                conversion.verify_source_loading(changed)

    def test_unknown_policy_fails_without_network(self):
        with self.assertRaisesRegex(ValueError, "snapshot policy"):
            stage("unused", snapshot_policy="ignore-all-unknown-keys")

    def test_create_once_roundtrip_preserves_source_and_strict_materialization(self):
        # Replace only external model loading and the fixed pin in this synthetic
        # fixture. No override is exposed by the production staging entrypoint.
        fake = types.ModuleType("transformers")
        fake.__version__ = "4.57.3"
        calls = []
        model = self.model
        def loader(folder, **kwargs):
            calls.append(kwargs)
            m = deepcopy(model)
            values = load((Path(folder) / "model.safetensors").read_bytes())
            m.load_state_dict({k: v for k, v in values.items() if k != conversion.BUFFER}, strict=True)
            return m, {k: [] for k in ("missing_keys", "mismatched_keys", "unexpected_keys", "error_msgs")}
        fake.AutoModel = types.SimpleNamespace(from_pretrained=loader)
        fake.AutoTokenizer = types.SimpleNamespace(from_pretrained=lambda *_, **__: lambda *a, **k: {})
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            src, out = root / "original", root / "derived"
            src.mkdir()
            for name in MODEL_FILES:
                (src / name).write_bytes(save(self.original, metadata={"format": "pt"}) if name == "model.safetensors" else b"{}")
            original_files = {p.name: p.read_bytes() for p in src.iterdir()}
            digest = hashlib.sha256(original_files["model.safetensors"]).hexdigest()
            with patch.dict(sys.modules, {"transformers": fake}), patch.object(conversion, "WEIGHTS_SHA256", digest):
                result = conversion.canonicalize(src, out)
                with self.assertRaises(ValueError):
                    conversion.canonicalize(src, out)
            self.assertEqual(original_files, {p.name: p.read_bytes() for p in src.iterdir()})
            self.assertTrue(result["derived_materialization"]["complete"])
            self.assertEqual(result["removed_runtime_buffers"], [conversion.BUFFER])
            self.assertFalse(result["production_authorized"])
            self.assertTrue(all(c["local_files_only"] and c["use_safetensors"] and not c["trust_remote_code"] for c in calls))
            self.assertEqual(set(load((out / "model.safetensors").read_bytes())), {"embeddings.weight"})
            with patch.dict(sys.modules, {"transformers": fake}), self.assertRaisesRegex(ValueError, "fixed published"):
                conversion.canonicalize(src, root / "wrong-pin")
            self.assertFalse((root / "wrong-pin").exists())


if __name__ == "__main__":
    unittest.main()
