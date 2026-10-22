"""Tiny modality-bank execution and fusion boundaries, not semantic evidence."""

from contextlib import contextmanager, redirect_stdout
import copy
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
import torch

from feature_bundle import FeatureBundleV1, FeatureIdentityV1
import multimodal_cohorts as cohorts
import multimodal_features as features
from real_encoder import canonical_sha256, physical_model_accounting


class TinyModule(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.vision_tower = torch.nn.Identity()
        self.register_buffer("scale", torch.ones(1))

    def forward(self, value, *, image):
        return self.vision_tower(value) if image else value


class TinyOwner:
    instances = []

    def __init__(self, **_kwargs):
        self._model = TinyModule().eval().requires_grad_(False)
        self.identity = FeatureIdentityV1("a" * 64, "b" * 40, "c" * 64)
        self.accounting = physical_model_accounting(self._model)
        self.load_ms, self.calls = 0.0, []
        self.instances.append(self)

    def encode_records(self, records, *, media_root, source_records):
        self.calls.append((copy.deepcopy(records), copy.deepcopy(source_records)))
        image = "image" in records[0]
        values = torch.zeros((len(records), 768))
        for i, record in enumerate(records):
            index = int(Path(record["image"]).stem) if image else int(record["text"].split()[-1])
            values[i, index] = 1.0
        values = self._model(values, image=image)
        bundle = FeatureBundleV1.from_tensors(global_features=values, identity=self.identity,
            source_record_digests=tuple(canonical_sha256({"input": r, "source": s})
                                        for r, s in zip(records, source_records)),
            missing_mask=torch.tensor([[False, not image, True, True, True]] * len(records)))
        self.last_receipt = {"encode_ms": .1, "forward_ms": .05, "batch_size": len(records),
                             "model_forward_calls": 1, "feature_bundle_sha256": bundle.bundle_digest}
        return bundle


class MultimodalFeaturesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous_threads = torch.get_num_threads()
        cls.addClassCleanup(torch.set_num_threads, cls.previous_threads)
        cls.root = Path(cls.enterClassContext(tempfile.TemporaryDirectory()))
        cls.cohorts_path = cls.root / "cohorts"
        cls.cohorts_path.mkdir()
        (cls.cohorts_path / "manifest.json").write_text('{"fixture":true}')
        pin = {"images": [{"image_id": i, "file_name": f"{i:012}.jpg",
                "image_sha256": canonical_sha256(["image", i]), "caption_id": 100 + i,
                "text": f"Human caption {i}", "text_sha256": canonical_sha256(["caption", i])}
                for i in range(1, 9)]}
        with patch.object(cohorts, "SPLIT_IMAGES", {k: 2 for k in ("train", "dev", "calibration", "test")}):
            cls.rows = cohorts.build_rows(pin)
        cls.bank_path = cls.root / "bank"
        with patch.object(cohorts, "load_cohorts", return_value=({"fixture": True}, cls.rows)), \
                patch.object(features, "FrozenRealEncoder", TinyOwner), redirect_stdout(io.StringIO()):
            cls.manifest = features.build_bank(cohorts=cls.cohorts_path, snapshot="fixture",
                inventory_sha256="d" * 64, output=cls.bank_path,
                operator_accepted_terms=True, threads=1, batch_size=2)
        cls.data_hash = features._sha((cls.cohorts_path / "manifest.json").read_bytes())
        cls.manifest_hash = features._sha((cls.bank_path / "manifest.json").read_bytes())
        cls.manifest, cls.bank = features.load_bank(cls.bank_path,
            expected_manifest_sha256=cls.manifest_hash, expected_data_sha256=cls.data_hash)
        cls.owner = TinyOwner.instances[-1]
        cls.test_rows = cls.rows["test"]

    @contextmanager
    def bank_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "bank"
            shutil.copytree(self.bank_path, target)
            yield target

    def test_build_encodes_each_original_caption_and_image_once_without_labels(self):
        self.assertEqual(self.manifest["observed_module_calls"], {"model": 8, "vision": 4})
        text, image = [], []
        for records, metadata in self.owner.calls:
            self.assertTrue(all("label" not in row and "row_id" not in row for row in metadata))
            for row in records:
                self.assertTrue(set(row).issubset({"text", "image"}))
                if "image" in row:
                    self.assertEqual(row["text"], features.IMAGE_PROMPT)
                    image.append(row["image"])
                else:
                    text.append(row["text"])
        self.assertEqual(len(text), len(set(text)))
        self.assertEqual(len(image), len(set(image)))
        self.assertEqual((len(text), len(image)), (8, 8))

    def test_source_indices_and_every_fusion_slice_match_the_actual_pair(self):
        bundle = features.pair_features(self.test_rows, self.manifest, self.bank, arm="text_image")
        actual = bundle.read_global()
        self.assertEqual(tuple(actual.shape), (4, 3073))
        for row, value in zip(self.test_rows, actual):
            text, image = torch.zeros(768), torch.zeros(768)
            text[row["source_caption_image_id"]] = 1
            image[row["image_id"]] = 1
            expected = torch.cat((text, image, text * image, (text - image).abs(),
                                  torch.tensor([float(row["source_caption_image_id"] == row["image_id"])])))
            self.assertTrue(torch.equal(value, expected))

    def test_arms_have_same_identity_and_budget_with_balanced_single_channel_marginals(self):
        bundles = {arm: features.pair_features(self.test_rows, self.manifest, self.bank, arm=arm)
                   for arm in features.ARMS}
        self.assertEqual(len({b.identity for b in bundles.values()}), 1)
        self.assertEqual({tuple(b.read_global().shape) for b in bundles.values()}, {(4, 3073)})
        for arm in ("text_only", "image_only"):
            values = bundles[arm].read_global()
            by_label = {label: sorted(v.numpy().tobytes() for r, v in zip(self.test_rows, values)
                                     if r["label"] == label) for label in (0, 1)}
            self.assertEqual(by_label[0], by_label[1])
        self.assertEqual(bundles["text_only"].snapshot()["missing_mask"][0].tolist(),
                         [False, True, True, True, True])
        self.assertEqual(bundles["image_only"].snapshot()["missing_mask"][0].tolist(),
                         [True, False, True, True, True])

    def test_missing_channels_remove_all_interactions_and_keep_shared_identity(self):
        for intervention, arm in (("missing_image", "text_only"), ("missing_text", "image_only")):
            missing = features.pair_features(self.test_rows, self.manifest, self.bank,
                                             arm="text_image", intervention=intervention)
            control = features.pair_features(self.test_rows, self.manifest, self.bank, arm=arm)
            self.assertTrue(torch.equal(missing.read_global(), control.read_global()))
            self.assertEqual(missing.identity, control.identity)
            self.assertEqual(int(torch.count_nonzero(missing.read_global()[:, 1536:])), 0)
        with self.assertRaises(ValueError):
            features.pair_features(self.test_rows, self.manifest, self.bank,
                                  arm="text_only", intervention="missing_text")

    def test_labels_and_row_ids_bind_provenance_without_entering_feature_numbers(self):
        original = features.pair_features(self.test_rows, self.manifest, self.bank, arm="text_image")
        changed_rows = [{**r, "label": 1 - r["label"], "row_id": "changed:" + r["row_id"]} for r in self.test_rows]
        changed = features.pair_features(changed_rows, self.manifest, self.bank, arm="text_image")
        self.assertTrue(torch.equal(original.read_global(), changed.read_global()))
        self.assertEqual(original.identity, changed.identity)
        self.assertNotEqual(original.source_record_digests, changed.source_record_digests)

    def test_within_block_swap_changes_row_association_but_preserves_input_multiset(self):
        original = features.pair_features(self.test_rows, self.manifest, self.bank, arm="text_image")
        swapped = features.pair_features(self.test_rows, self.manifest, self.bank,
                                          arm="text_image", intervention="shuffled_image")
        left, right = original.read_global(), swapped.read_global()
        self.assertTrue(torch.equal(left[:, :768], right[:, :768]))
        self.assertFalse(torch.equal(left[:, 768:1536], right[:, 768:1536]))
        self.assertEqual(sorted(x.numpy().tobytes() for x in left), sorted(x.numpy().tobytes() for x in right))
        blocks = {}
        for row in self.test_rows:
            blocks.setdefault(row["pair_block_id"], set()).add(row["image_id"])
        for row, value in zip(self.test_rows, right):
            expected = next(i for i in blocks[row["pair_block_id"]] if i != row["image_id"])
            self.assertEqual(int(value[768:1536].argmax()), expected)
        with self.assertRaises(ValueError):
            features.pair_features(self.test_rows[:1], self.manifest, self.bank,
                                  arm="text_image", intervention="shuffled_image")

    def test_cached_tensor_mutation_cannot_keep_the_old_source_binding(self):
        corrupted = {k: v.clone() for k, v in self.bank.items()}
        corrupted["image"][0, 0] += 1
        with self.assertRaisesRegex(ValueError, "tensor"):
            features.pair_features(self.test_rows, self.manifest, corrupted, arm="text_image")

    def test_external_manifest_and_data_hash_are_required(self):
        for manifest_hash, data_hash in (("0" * 64, self.data_hash), (self.manifest_hash, "0" * 64)):
            with self.assertRaises(ValueError):
                features.load_bank(self.bank_path, expected_manifest_sha256=manifest_hash,
                                   expected_data_sha256=data_hash)

    def test_current_source_code_drift_rejects_precomputed_cache(self):
        with patch.object(features, "bank_code_identity", return_value={"changed": "0" * 64}):
            with self.assertRaises(ValueError):
                features.load_bank(self.bank_path, expected_manifest_sha256=self.manifest_hash,
                                   expected_data_sha256=self.data_hash)

    def test_truncated_provenance_rejected_even_under_new_manifest_pin(self):
        with self.bank_copy() as directory:
            manifest = json.loads((directory / "manifest.json").read_bytes())
            manifest["provenance"]["text"].pop()
            raw = features._json(manifest) + b"\n"
            (directory / "manifest.json").write_bytes(raw)
            with self.assertRaises(ValueError):
                features.load_bank(directory, expected_manifest_sha256=features._sha(raw),
                                   expected_data_sha256=self.data_hash)

    def test_oversized_npy_header_is_rejected_before_numpy_allocation(self):
        with self.bank_copy() as directory:
            output = io.BytesIO()
            with zipfile.ZipFile(directory / "features.npz") as old, zipfile.ZipFile(output, "w") as new:
                for name in old.namelist():
                    if name == "image.npy":
                        header = io.BytesIO()
                        np.lib.format.write_array_header_1_0(header,
                            {"descr": "<f4", "fortran_order": False, "shape": (10**12, 768)})
                        new.writestr(name, header.getvalue())
                    else:
                        new.writestr(name, old.read(name))
            (directory / "features.npz").write_bytes(output.getvalue())
            manifest = json.loads((directory / "manifest.json").read_bytes())
            manifest["features_sha256"] = features._sha(output.getvalue())
            raw = features._json(manifest) + b"\n"
            (directory / "manifest.json").write_bytes(raw)
            with patch.object(features.np, "load", side_effect=AssertionError("allocation reached")):
                with self.assertRaises(ValueError):
                    features.load_bank(directory, expected_manifest_sha256=features._sha(raw),
                                       expected_data_sha256=self.data_hash)


if __name__ == "__main__":
    unittest.main()
