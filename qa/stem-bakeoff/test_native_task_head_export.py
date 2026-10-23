"""Native artifact boundary checks; tiny fixtures are not quality evidence."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import numpy as np
import torch

from cell_head_training import (HeadCohortV1, HeadTrainingConfigV1,
                                save_head_artifact, train_cell_head)
from export_native_task_head_v1 import TENSOR_ORDER, export_native_head
from feature_bundle import FeatureBundleV1, FeatureIdentityV1


def _sha(value):
    return hashlib.sha256(value).hexdigest()


IDENTITY = FeatureIdentityV1(encoder_sha256=_sha(b"encoder"),
    checkpoint_revision="1" * 40, preprocess_sha256=_sha(b"fusion"))


def _cohort(name, width=9):
    features = torch.randn((8, width), generator=torch.Generator().manual_seed(3))
    mask = torch.ones((8, 5), dtype=torch.bool)
    mask[:, :2] = False
    bundle = FeatureBundleV1.from_tensors(global_features=features,
        source_record_digests=tuple(_sha(f"{name}:{i}".encode()) for i in range(8)),
        identity=IDENTITY, missing_mask=mask)
    return HeadCohortV1(bundle, tuple(i % 2 for i in range(8)),
                        tuple(f"{name}:{i}" for i in range(8)))


def _train(width=9):
    return train_cell_head(_cohort("train", width), _cohort("cal", width),
        {"test": _cohort("test", width)}, config=HeadTrainingConfigV1(
            task_count=2, steps=2, adapter_rank=2, state_width=2))


class NativeTaskHeadExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.threads = torch.get_num_threads()
        torch.set_num_threads(1)
        cls.trained = _train()

    @classmethod
    def tearDownClass(cls):
        torch.set_num_threads(cls.threads)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        self.saved = save_head_artifact(self.trained, self.source)

    def export(self, **overrides):
        arguments = {"expected_manifest_sha256": self.saved["manifest_sha256"],
                     "expected_identity": IDENTITY, "output": self.root / "native"}
        arguments.update(overrides)
        return export_native_head(self.source, **arguments)

    def test_exported_payload_matches_active_tensors_and_leaves_source_unchanged(self):
        before = {p.name: p.read_bytes() for p in self.source.iterdir()}
        receipt = self.export()
        manifest_bytes = (self.root / "native/manifest.json").read_bytes()
        payload = (self.root / "native/weights.f32le").read_bytes()
        manifest = json.loads(manifest_bytes)
        self.assertEqual(receipt["manifest_sha256"], _sha(manifest_bytes))
        self.assertEqual(receipt["weights_sha256"], _sha(payload))
        expected = np.concatenate([self.trained._head.state_dict()[name].numpy().ravel()
                                   for name in TENSOR_ORDER])
        np.testing.assert_array_equal(np.frombuffer(payload, dtype="<f4"), expected)
        self.assertLess(len(payload), sum(value.numel() * 4 for value in
                                         self.trained._head.state_dict().values()))
        self.assertEqual(manifest["source_head_manifest_sha256"], self.saved["manifest_sha256"])
        self.assertEqual(manifest["required_present_mask"], 3)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.source.iterdir()})

    def test_retained_hash_and_complete_identity_are_required(self):
        for overrides in ({"expected_manifest_sha256": "0" * 64},
                          {"expected_identity": replace(IDENTITY, revocation_epoch=1)}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self.export(**overrides)
            self.assertFalse((self.root / "native").exists())

    def test_source_tensor_tampering_does_not_create_native_artifact(self):
        path = self.source / "weights.npz"
        raw = bytearray(path.read_bytes())
        raw[len(raw) // 2] ^= 1
        path.write_bytes(raw)
        with self.assertRaises(ValueError):
            self.export()
        self.assertFalse((self.root / "native").exists())

    def test_output_is_create_only(self):
        self.export()
        previous = (self.root / "native/manifest.json").read_bytes()
        with self.assertRaises(ValueError):
            self.export()
        self.assertEqual(previous, (self.root / "native/manifest.json").read_bytes())

    def test_re_pinned_nonzero_state_declaration_is_not_supported(self):
        path = self.source / "manifest.json"
        manifest = json.loads(path.read_bytes())
        manifest["report"]["local_state_training"] = "stateful_policy"
        raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        path.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, "zero-state"):
            self.export(expected_manifest_sha256=_sha(raw))
        self.assertFalse((self.root / "native").exists())

    def test_nonfusion_dimensions_are_not_exported_as_text_image_fusion(self):
        shutil.rmtree(self.source)
        self.saved = save_head_artifact(_train(width=6), self.source)
        with self.assertRaisesRegex(ValueError, "fusion"):
            self.export()
        self.assertFalse((self.root / "native").exists())


if __name__ == "__main__":
    unittest.main()
