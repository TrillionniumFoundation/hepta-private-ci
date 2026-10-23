"""Handmade data-contract checks; these tests never access Fashion files."""

import gzip
import hashlib
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock

import numpy as np

from fashion_research import data


def _idx(images, labels):
    image_bytes = struct.pack(">IIII", 2051, len(images), 28, 28) + images.tobytes()
    label_bytes = struct.pack(">II", 2049, len(labels)) + labels.tobytes()
    return image_bytes, label_bytes


def _identity(row):
    pixel_hash = hashlib.sha256(row.tobytes()).digest()
    split_number = int.from_bytes(
        hashlib.sha256(b"hepta-fashion-split-v1\0" + pixel_hash).digest(), "big"
    ) % 6
    split = "FIT" if split_number < 4 else ("SELECT" if split_number == 4 else "SCREEN")
    policy_rank = hashlib.sha256(b"hepta-fashion-policy-v1\0" + pixel_hash).digest()
    fold = int.from_bytes(
        hashlib.sha256(b"hepta-fashion-oof-v1\0" + pixel_hash).digest(), "big"
    ) % 3
    return pixel_hash.hex(), split, policy_rank, fold


def _hand_grid(*, fit_folds=None):
    images = np.zeros((1400, 784), dtype=np.uint8)
    for index in range(len(images)):
        images[index, :8] = np.frombuffer(index.to_bytes(8, "little"), dtype=np.uint8)
        images[index, 8:] = (index * 37 + np.arange(776)) % 256
    facts = [_identity(row) for row in images]
    if fit_folds is not None:
        retained = [i for i, fact in enumerate(facts)
                    if fact[1] != "FIT" or fact[3] in fit_folds]
        images = images[retained]
        facts = [facts[i] for i in retained]
    fit = [i for i, fact in enumerate(facts) if fact[1] == "FIT"]
    policy = sorted(fit, key=lambda i: facts[i][2])[:64]
    policy_set = set(policy)
    labels = np.zeros(len(images), dtype=np.uint8)
    partitions = [policy, [i for i in fit if i not in policy_set]]
    partitions += [[i for i, fact in enumerate(facts) if fact[1] == split]
                   for split in ("SELECT", "SCREEN")]
    for indices in partitions:
        assert len(indices) >= 10, "the hand fixture needs all ten classes"
        labels[indices] = np.arange(len(indices)) % 10
    return images, labels


def _noise_reference(images):
    result = []
    for row in images:
        pixel_hash = hashlib.sha256(row.tobytes()).digest()
        digest = hashlib.sha256(b"hepta-fashion-noise-v1\0" + pixel_hash).digest()
        seed = int.from_bytes(digest[:16], "big")
        epsilon = np.random.Generator(np.random.PCG64DXSM(seed)).standard_normal(784)
        values = row.astype(np.float64) / 255.0 + 0.2 * epsilon
        result.append(np.clip(values, 0.0, 1.0).astype(np.float32))
    return np.stack(result)


class FashionIdxTests(unittest.TestCase):
    def setUp(self):
        self.images = np.arange(2 * 784, dtype=np.uint16).astype(np.uint8).reshape(2, 784)
        self.labels = np.array([0, 9], dtype=np.uint8)
        self.image_bytes, self.label_bytes = _idx(self.images, self.labels)

    def test_idx_decodes_exact_handmade_bytes_and_uint8_shape(self):
        images, labels = data.parse_idx(self.image_bytes, self.label_bytes, expected_rows=2)
        self.assertEqual(images.dtype, np.uint8)
        self.assertEqual(images.shape, (2, 784))
        self.assertEqual(labels.dtype, np.uint8)
        self.assertEqual(labels.shape, (2,))
        self.assertEqual(images.tobytes(), self.images.tobytes())
        self.assertEqual(labels.tobytes(), self.labels.tobytes())

    def test_idx_rejects_wrong_magic_dimensions_counts_lengths_and_labels(self):
        cases = {
            "image magic": (struct.pack(">I", 2050) + self.image_bytes[4:], self.label_bytes),
            "label magic": (self.image_bytes, struct.pack(">I", 2051) + self.label_bytes[4:]),
            "image rows": (self.image_bytes[:8] + struct.pack(">II", 27, 28)
                           + self.image_bytes[16:], self.label_bytes),
            "image columns": (self.image_bytes[:8] + struct.pack(">II", 28, 29)
                              + self.image_bytes[16:], self.label_bytes),
            "image count": (self.image_bytes[:4] + struct.pack(">I", 3)
                            + self.image_bytes[8:], self.label_bytes),
            "label count": (self.image_bytes, self.label_bytes[:4] + struct.pack(">I", 1)
                            + self.label_bytes[8:]),
            "short image header": (self.image_bytes[:15], self.label_bytes),
            "short label header": (self.image_bytes, self.label_bytes[:7]),
            "short image body": (self.image_bytes[:-1], self.label_bytes),
            "short label body": (self.image_bytes, self.label_bytes[:-1]),
            "trailing image": (self.image_bytes + b"\0", self.label_bytes),
            "trailing label": (self.image_bytes, self.label_bytes + b"\0"),
            "label ten": (self.image_bytes, self.label_bytes[:-1] + bytes([10])),
            "label 255": (self.image_bytes, self.label_bytes[:-1] + bytes([255])),
        }
        for fault, (images, labels) in cases.items():
            with self.subTest(fault=fault), self.assertRaises(ValueError):
                data.parse_idx(images, labels, expected_rows=2)

    def test_idx_requires_the_declared_row_count(self):
        with self.assertRaises(ValueError):
            data.parse_idx(self.image_bytes, self.label_bytes, expected_rows=3)
        with self.assertRaises(ValueError):
            data.parse_idx(self.image_bytes, self.label_bytes)


class FashionNoiseTests(unittest.TestCase):
    def test_noise_matches_independent_sha_pcg_float64_then_float32_reference(self):
        images = np.stack((np.zeros(784, dtype=np.uint8),
                           np.full(784, 255, dtype=np.uint8),
                           np.arange(784, dtype=np.uint16).astype(np.uint8)))
        saved = images.copy()
        actual = data.noisy_images(images)
        expected = _noise_reference(images)
        self.assertEqual(actual.dtype, np.float32)
        self.assertEqual(actual.shape, images.shape)
        self.assertEqual(actual.tobytes(), expected.tobytes())
        self.assertEqual(images.tobytes(), saved.tobytes())
        self.assertTrue(np.any(actual == 0))
        self.assertTrue(np.any(actual == 1))

    def test_noise_is_duplicate_order_and_batch_independent(self):
        images, _ = _hand_grid()
        rows = images[[4, 17, 4, 120]]
        original = data.noisy_images(rows)
        order = np.array([3, 0, 2, 1])
        self.assertEqual(data.noisy_images(rows[order]).tobytes(), original[order].tobytes())
        self.assertEqual(original[0].tobytes(), original[2].tobytes())
        for index, row in enumerate(rows):
            self.assertEqual(data.noisy_images(row[None]).tobytes(), original[index:index + 1].tobytes())

    def test_noise_rejects_non_uint8_or_wrong_image_shape(self):
        for images in (np.zeros((2, 784), dtype=np.float32),
                       np.zeros((2, 28, 28), dtype=np.uint8),
                       np.zeros((2, 783), dtype=np.uint8),
                       np.zeros(784, dtype=np.uint8)):
            with self.subTest(shape=images.shape, dtype=images.dtype), self.assertRaises(ValueError):
                data.noisy_images(images)


class FashionMetadataTests(unittest.TestCase):
    def test_metadata_matches_full_digest_splits_policy_order_and_group_folds(self):
        images, labels = _hand_grid()
        metadata = data._metadata(images, labels, policy_groups=64)
        facts = [_identity(row) for row in images]
        expected_indices = {split: [i for i, fact in enumerate(facts) if fact[1] == split]
                            for split in ("FIT", "SELECT", "SCREEN")}
        policy = sorted(expected_indices["FIT"], key=lambda i: facts[i][2])[:64]
        expected_indices["POLICY"] = sorted(policy)
        policy_set = set(policy)
        self.assertEqual(len(metadata["rows"]), len(images))
        for split, indices in expected_indices.items():
            self.assertEqual(sorted(metadata["indices"][split]), indices)
            self.assertEqual(set(int(labels[i]) for i in indices), set(range(10)))
            expected_counts = np.bincount(labels[indices], minlength=10).tolist()
            self.assertEqual(metadata["counts"][split], {
                "rows": len(indices), "class_counts": expected_counts, "groups": len(indices)})
        self.assertEqual(metadata["policy_group_order"], [facts[i][0] for i in policy])
        for fold in range(3):
            held = [i for i in policy if facts[i][3] == fold]
            trained = [i for i in policy if facts[i][3] != fold]
            actual = metadata["oof"][str(fold)]
            self.assertEqual(actual["hold_indices"], held)
            self.assertEqual(actual["train_indices"], trained)
            self.assertEqual(actual["hold_class_counts"],
                             np.bincount(labels[held], minlength=10).tolist())
            self.assertEqual(actual["train_class_counts"],
                             np.bincount(labels[trained], minlength=10).tolist())
        for index, (pixel_hash, split, _, fold) in enumerate(facts):
            row = metadata["rows"][index]
            self.assertEqual(row["row_id"], index)
            self.assertEqual(row["pixel_sha256"], pixel_hash)
            self.assertEqual(row["split"], split)
            self.assertEqual(row["policy_group"], index in policy_set)
            self.assertEqual(row["fold"], fold)
            group = metadata["groups"][pixel_hash]
            self.assertEqual(group["indices"], [index])
            self.assertEqual(group["multiplicity"], 1)
            self.assertFalse(group["conflicting_labels"])
            self.assertEqual(group["split"], split)
            self.assertEqual(group["policy_group"], index in policy_set)
            self.assertEqual(group["fold"], fold)

    def test_default_policy_uses_512_unique_groups(self):
        images, labels = _hand_grid()
        metadata = data._metadata(images, labels)
        selected = {metadata["rows"][i]["pixel_sha256"] for i in metadata["indices"]["POLICY"]}
        self.assertEqual(len(selected), 512)
        self.assertTrue(all(metadata["groups"][key]["split"] == "FIT" for key in selected))

    def test_duplicates_and_conflicting_labels_keep_original_multiplicity(self):
        images, labels = _hand_grid()
        original = data._metadata(images, labels, policy_groups=64)
        duplicate_index = original["indices"]["POLICY"][0]
        images = np.concatenate((images, images[[duplicate_index, duplicate_index]]))
        conflicting = (int(labels[duplicate_index]) + 1) % 10
        labels = np.concatenate((labels, np.array([labels[duplicate_index], conflicting], dtype=np.uint8)))
        metadata = data._metadata(images, labels, policy_groups=64)
        pixel_hash = _identity(images[duplicate_index])[0]
        group = metadata["groups"][pixel_hash]
        expected_indices = [duplicate_index, len(images) - 2, len(images) - 1]
        self.assertEqual(group["indices"], expected_indices)
        self.assertEqual(group["multiplicity"], 3)
        self.assertTrue(group["conflicting_labels"])
        self.assertEqual(set(group["labels"]), {int(labels[duplicate_index]), conflicting})
        self.assertTrue(set(expected_indices).issubset(metadata["indices"]["POLICY"]))
        self.assertEqual(len(metadata["rows"]), len(images))
        self.assertEqual(labels[-1], conflicting)
        self.assertEqual(len(metadata["indices"]["POLICY"]), 66)
        self.assertEqual(metadata["duplicate_rows"], 2)
        self.assertEqual(metadata["conflicting_label_groups"], [pixel_hash])
        self.assertEqual(metadata["counts"]["POLICY"]["rows"], 66)
        self.assertEqual(metadata["counts"]["POLICY"]["groups"], 64)
        self.assertEqual(metadata["counts"]["POLICY"]["class_counts"],
                         np.bincount(labels[metadata["indices"]["POLICY"]], minlength=10).tolist())

    def test_reordering_rows_preserves_group_membership_policy_and_folds(self):
        images, labels = _hand_grid()
        first = data._metadata(images, labels, policy_groups=64)
        order = np.random.Generator(np.random.PCG64DXSM(73)).permutation(len(images))
        second = data._metadata(images[order], labels[order], policy_groups=64)
        self.assertEqual(set(first["groups"]), set(second["groups"]))
        for pixel_hash, group in first["groups"].items():
            other = second["groups"][pixel_hash]
            for key in ("split", "policy_group", "fold", "multiplicity", "conflicting_labels"):
                self.assertEqual(group[key], other[key])
            self.assertEqual(set(group["labels"]), set(other["labels"]))
            self.assertEqual({int(order[i]) for i in other["indices"]}, set(group["indices"]))

    def test_each_split_and_policy_must_retain_all_ten_classes(self):
        images, labels = _hand_grid()
        valid = data._metadata(images, labels, policy_groups=64)
        for split in ("FIT", "SELECT", "SCREEN", "POLICY"):
            changed = labels.copy()
            for index in valid["indices"][split]:
                if changed[index] == 9:
                    changed[index] = 8
            with self.subTest(split=split), self.assertRaises(ValueError):
                data._metadata(images, changed, policy_groups=64)

    def test_empty_oof_holdout_or_training_is_rejected(self):
        for folds in ({0, 1}, {1}):
            images, labels = _hand_grid(fit_folds=folds)
            with self.subTest(folds=folds), self.assertRaises(ValueError):
                data._metadata(images, labels, policy_groups=64)

    def test_oof_fold_missing_one_class_is_retained_instead_of_rejected(self):
        images, labels = _hand_grid()
        metadata = data._metadata(images, labels, policy_groups=64)
        policy = metadata["indices"]["POLICY"]
        for index in policy:
            if labels[index] == 9:
                labels[index] = 8
        chosen = next(index for index in policy if _identity(images[index])[3] == 0)
        labels[chosen] = 9
        result = data._metadata(images, labels, policy_groups=64)
        for fold in (1, 2):
            held = [i for i in result["indices"]["POLICY"] if result["rows"][i]["fold"] == fold]
            self.assertTrue(held)
            self.assertNotIn(9, set(int(labels[i]) for i in held))
            self.assertEqual(result["oof"][str(fold)]["hold_class_counts"][9], 0)

    def test_metadata_rejects_wrong_label_dtype_shape_range_and_small_policy(self):
        images, labels = _hand_grid()
        for invalid in (labels.astype(np.int64), labels[:, None], labels[:-1],
                        np.full(len(labels), 10, dtype=np.uint8)):
            with self.subTest(shape=invalid.shape, dtype=invalid.dtype), self.assertRaises(ValueError):
                data._metadata(images, invalid, policy_groups=64)
        with self.assertRaises(ValueError):
            data._metadata(images, labels, policy_groups=9)


class FashionLocalLoaderTests(unittest.TestCase):
    def test_corrupt_handmade_gzip_fails_hash_without_reading_other_files(self):
        images = np.zeros((2, 784), dtype=np.uint8)
        labels = np.array([0, 1], dtype=np.uint8)
        image_bytes, label_bytes = _idx(images, labels)
        names = ("train-images-idx3-ubyte.gz", "train-labels-idx1-ubyte.gz")
        reads = []
        original_open = Path.open

        def track_open(path, *args, **kwargs):
            reads.append(path.name)
            self.assertIn(path.name, names)
            return original_open(path, *args, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            for name, payload in zip(names, (image_bytes, label_bytes)):
                (Path(directory) / name).write_bytes(gzip.compress(payload, mtime=0))
            (Path(directory) / "t10k-images-idx3-ubyte.gz").write_bytes(b"forbidden hand sentinel")
            with mock.patch.object(Path, "open", track_open), self.assertRaises(ValueError):
                data.load_train(directory)
        self.assertTrue(reads)
        self.assertTrue(set(reads).issubset(names))

    def test_handmade_loader_records_observed_and_optional_pinned_sha_and_fit_only_cache(self):
        images, labels = _hand_grid()
        names = ("train-images-idx3-ubyte.gz", "train-labels-idx1-ubyte.gz")
        compressed = {name: gzip.compress(payload, mtime=0)
                      for name, payload in zip(names, _idx(images, labels))}
        hand_md5 = {name: hashlib.md5(payload).hexdigest() for name, payload in compressed.items()}
        hand_sha = {name: hashlib.sha256(payload).hexdigest() for name, payload in compressed.items()}
        with tempfile.TemporaryDirectory() as directory:
            for name, payload in compressed.items():
                (Path(directory) / name).write_bytes(payload)
            with mock.patch.object(data, "EXPECTED_ROWS", len(images)), \
                    mock.patch.object(data, "OFFICIAL_MD5", hand_md5):
                observed = data.load_train(directory)
                pinned = data.load_train(directory, expected_sha256=hand_sha, cache_noisy=True)
                wrong_sha = {**hand_sha, names[0]: "0" * 64}
                with self.assertRaises(ValueError):
                    data.load_train(directory, expected_sha256=wrong_sha)
        self.assertEqual(observed["images"].tobytes(), images.tobytes())
        self.assertEqual(observed["labels"].tobytes(), labels.tobytes())
        self.assertIsNone(observed["noisy"])
        self.assertIsNone(observed["noisy_indices"])
        self.assertFalse(observed["metadata"]["official_TEST_accessed"])
        for name in names:
            unpinned_file = observed["metadata"]["files"][name]
            pinned_file = pinned["metadata"]["files"][name]
            self.assertEqual(unpinned_file["md5"], hand_md5[name])
            self.assertTrue(unpinned_file["publisher_md5_verified"])
            self.assertEqual(unpinned_file["sha256"], hand_sha[name])
            self.assertIsNone(unpinned_file["expected_sha256"])
            self.assertFalse(unpinned_file["sha256_pin_verified"])
            self.assertEqual(pinned_file["expected_sha256"], hand_sha[name])
            self.assertTrue(pinned_file["sha256_pin_verified"])
        np.testing.assert_array_equal(pinned["noisy_indices"], pinned["indices"]["FIT"])
        self.assertEqual(pinned["noisy"].tobytes(),
                         _noise_reference(images[pinned["indices"]["FIT"]]).tobytes())
        self.assertFalse(set(pinned["noisy_indices"]) & set(pinned["indices"]["SCREEN"]))

    def test_sha_pin_names_cannot_add_a_test_or_arbitrary_file(self):
        pins = {name: "0" * 64 for name in data.OFFICIAL_MD5}
        for invalid in ({}, {**pins, "t10k-images-idx3-ubyte.gz": "0" * 64},
                        {next(iter(pins)): "0" * 64},
                        {name: "A" * 64 for name in pins}):
            with self.subTest(pins=invalid), self.assertRaises(ValueError):
                data.load_train("/unused-handmade-path", expected_sha256=invalid)


class FashionServiceInputTests(unittest.TestCase):
    def test_service_input_contains_only_copied_noisy_pixels_and_fixed_sigma(self):
        noisy = np.full((2, 784), 0.5, dtype=np.float32)
        value = data.service_input(noisy)
        self.assertEqual(set(value), {"noisy", "sigma"})
        self.assertEqual(value["sigma"], 0.2)
        self.assertFalse(value["noisy"].flags.writeable)
        self.assertFalse(np.shares_memory(value["noisy"], noisy))
        noisy[0, 0] = 0
        self.assertEqual(value["noisy"][0, 0], 0.5)

    def test_service_input_rejects_wrong_dtype_shape_and_nonfinite_or_out_of_range(self):
        for value in (np.zeros((1, 784), dtype=np.float64),
                      np.zeros((1, 28, 28), dtype=np.float32),
                      np.full((1, 784), np.nan, dtype=np.float32),
                      np.full((1, 784), -0.01, dtype=np.float32),
                      np.full((1, 784), 1.01, dtype=np.float32)):
            with self.subTest(shape=value.shape, dtype=value.dtype), self.assertRaises(ValueError):
                data.service_input(value)


if __name__ == "__main__":
    unittest.main()
