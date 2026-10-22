"""Probe boundary tests with small tensors, not evidence of model quality."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import torch

from feature_bundle import FeatureBundleError, FeatureBundleV1, FeatureIdentityV1
from real_encoder import RealEncoderError, canonical_sha256, source_digests
from real_media_probe import (MediaProbeError, SOURCE_RECORD, TEXT, create_fixture,
                              input_tensor_manifest, inspect_bundle, run_probe, save_views)
from teacher_forward import validate_records


class RealMediaProbeTests(unittest.TestCase):
    def setUp(self):
        self.identity = FeatureIdentityV1("1" * 64, "2" * 40, "3" * 64)
        self.source = "4" * 64

    def bundle(self, **overrides):
        tensors = {"global_features": torch.nn.functional.normalize(torch.ones(1, 768), dim=-1),
                   "token_features": torch.arange(4 * 768, dtype=torch.float32).reshape(1, 4, 768),
                   "token_valid": torch.tensor([[True, True, True, False]]),
                   "modality_ids": torch.tensor([[0, 1, 1, -1]]),
                   "missing_mask": torch.tensor([[False, False, True, True, True]])}
        tensors.update(overrides)
        return FeatureBundleV1.from_tensors(
            **tensors, identity=self.identity, source_record_digests=(self.source,))

    def inspect(self, bundle, **overrides):
        args = {"expected_identity": self.identity, "expected_source": self.source,
                "model_calls": 1, "vision_calls": 1}
        args.update(overrides)
        return inspect_bundle(bundle, **args)

    def test_program_image_binding_matches_sealed_media_record_protocol(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            record, source = create_fixture(directory)
            image_path = Path(directory) / record["image"]
            with Image.open(image_path) as image:
                self.assertEqual((image.mode, image.size), ("RGB", (256, 256)))
                self.assertEqual(image.getpixel((50, 90)), (220, 30, 40))
                self.assertEqual(image.getpixel((184, 104)), (30, 60, 220))
            conversations, digest = validate_records([record], directory, "embeddinggemma2_740m")
            bound = [(part["type"], hashlib.sha256(
                part["text"].encode() if part["type"] == "text"
                else Path(part["url"]).read_bytes()).hexdigest())
                for part in conversations[0][0]["content"]]
            self.assertEqual(digest, canonical_sha256([bound]))
            self.assertEqual(source["image_file_sha256"], hashlib.sha256(image_path.read_bytes()).hexdigest())
            self.assertEqual(source["expected_source_record_sha256"], canonical_sha256({
                "text_source": source_digests([TEXT], [SOURCE_RECORD])[0], "media_sources": bound}))
            image_path.write_bytes(image_path.read_bytes() + b"changed")
            _, changed = validate_records([record], directory, "embeddinggemma2_740m")
            self.assertNotEqual(digest, changed)

    def test_token_evidence_is_saved_losslessly_and_cannot_replace_prior_evidence(self):
        bundle = self.bundle()
        summary, views = self.inspect(bundle)
        self.assertEqual(summary["valid_token_counts_by_modality"],
                         {"text": 1, "image": 2, "audio": 0, "video": 0, "ui_event": 0})
        self.assertEqual(summary["padding_token_count"], 1)
        self.assertEqual(summary["feature_payload_bytes"],
                         sum(value.numel() * value.element_size() for value in views.values()))
        with tempfile.TemporaryDirectory() as directory:
            saved = save_views(directory, views)
            for name, entry in saved.items():
                path = Path(directory) / entry["file"]
                np.testing.assert_array_equal(np.load(path, allow_pickle=False), views[name].numpy())
                self.assertEqual(entry["file_sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
                self.assertEqual(entry["bytes"], path.stat().st_size)
            with self.assertRaises(FileExistsError):
                save_views(directory, views)

    def test_wrong_input_record_and_preprocessing_identity_are_rejected(self):
        bundle = self.bundle()
        with self.assertRaisesRegex(MediaProbeError, "actual text/image"):
            self.inspect(bundle, expected_source="5" * 64)
        with self.assertRaises(FeatureBundleError):
            self.inspect(bundle, expected_identity=replace(self.identity, preprocess_sha256="6" * 64))

    def test_skipped_or_repeated_model_and_vision_calls_cannot_pass(self):
        for model, vision in ((0, 1), (1, 0), (2, 1), (1, 2)):
            with self.subTest(model=model, vision=vision), self.assertRaises(MediaProbeError):
                self.inspect(self.bundle(), model_calls=model, vision_calls=vision)

    def test_pooled_only_or_text_only_markers_cannot_prove_image_execution(self):
        pooled = self.bundle(token_features=None, token_valid=None, modality_ids=None)
        with self.assertRaisesRegex(MediaProbeError, "token views"):
            self.inspect(pooled)
        text_only = self.bundle(modality_ids=torch.tensor([[0, 0, 0, -1]]))
        with self.assertRaisesRegex(MediaProbeError, "both text and image"):
            self.inspect(text_only)
        with self.assertRaisesRegex(MediaProbeError, "presence"):
            self.inspect(self.bundle(missing_mask=torch.tensor([[False, False, False, True, True]])))

    def test_unattested_region_and_time_annotations_are_not_promoted(self):
        for name, mask, width in (("region_boxes", "region_valid", 4), ("time_spans", "time_valid", 2)):
            bundle = self.bundle(**{name: torch.zeros(1, 4, width), mask: torch.zeros(1, 4, dtype=torch.bool)})
            with self.subTest(view=name), self.assertRaisesRegex(MediaProbeError, "region or time"):
                self.inspect(bundle)

    def test_model_input_payload_binds_values_and_deduplicates_storage(self):
        tensor = torch.arange(6, dtype=torch.float32)
        inputs = {"pixel_values": tensor.reshape(1, 2, 3), "alias": tensor[:3],
                  "input_ids": torch.tensor([[7, 8]], dtype=torch.int64)}
        before = input_tensor_manifest(inputs)
        self.assertEqual(before["tensor_payload_bytes"], 24 + 12 + 16)
        self.assertEqual(before["unique_input_storage_bytes"], 24 + 16)
        tensor[0] = 100
        after = input_tensor_manifest(inputs)
        self.assertNotEqual(before["tensors"]["pixel_values"]["bytes_sha256"],
                            after["tensors"]["pixel_values"]["bytes_sha256"])
        self.assertEqual(before["tensors"]["input_ids"], after["tensors"]["input_ids"])

    def test_failed_checkpoint_load_leaves_failure_without_execution_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "evidence"
            with patch("real_media_probe.FrozenRealEncoder", side_effect=RealEncoderError("wrong snapshot")):
                with self.assertRaisesRegex(RealEncoderError, "wrong snapshot"):
                    run_probe(snapshot=Path(directory) / "missing", expected_inventory_sha256="7" * 64,
                              output=output, operator_accepted_terms=True)
            self.assertFalse((output / "receipt.json").exists())
            failure = json.loads((output / "failure.json").read_text())
            self.assertEqual((failure["status"], failure["error_type"], failure["reason"]),
                             ("FAILED", "RealEncoderError", "wrong snapshot"))
            self.assertFalse(failure["multimodal_quality_qualified"])


if __name__ == "__main__":
    unittest.main()
