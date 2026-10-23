import copy
import unittest
from unittest.mock import patch

import numpy as np

from data import attributes
from data_v2 import dataset, default_profile, manifest


class IndependentDataTests(unittest.TestCase):
    def setUp(self):
        self.profile = default_profile()
        self.profile["sources_per_class"] = {"train": 2, "validation": 1, "test": 1}
        self.profile["instructions_per_source"] = 5

    def test_physical_source_groups_and_input_bytes_are_disjoint(self):
        train = dataset("train", self.profile)
        validation = dataset("validation", self.profile)
        self.assertFalse(set(train["source_ids"]) & set(validation["source_ids"]))
        self.assertFalse(set(train["input_hashes"]) & set(validation["input_hashes"]))
        self.assertEqual(train["source_ids"], train["groups"])
        self.assertEqual(set(train["labels"]), set(range(12)))
        source_counts = {source: train["source_ids"].count(source) for source in train["sources"]}
        self.assertEqual(set(source_counts.values()), {10})
        for source in train["sources"]:
            rows = np.asarray(train["source_ids"]) == source
            self.assertEqual(len(np.unique(train["commands"][rows], axis=0)), 5)
            self.assertEqual(len(np.unique(train["source_scenes"][rows])), 1)

    def test_instructions_and_targets_use_source_semantics_without_label_features(self):
        data = dataset("train", self.profile)
        expected = []
        for scene, command in zip(data["source_scenes"], data["commands"]):
            color, shape, position = attributes(scene)
            c, s, p = command
            target = ((color if c == 0 else c - 1) * 2 + (shape if s == 0 else s - 1)) * 2
            expected.append(target + (position if p == 0 else p - 1))
        np.testing.assert_array_equal(data["labels"], expected)
        words = np.concatenate((np.eye(4)[data["commands"][:, 0]],
                                np.eye(3)[data["commands"][:, 1]],
                                np.eye(3)[data["commands"][:, 2]]), axis=1)
        self.assertEqual(data["full"].shape, (240, 202))
        np.testing.assert_array_equal(data["full"][:, 192:], words)
        np.testing.assert_array_equal(data["low"][:, 192:], words)
        image = data["full"][:, :192].reshape(-1, 8, 8, 3)
        thumbnail = image.reshape(-1, 4, 2, 4, 2, 3).mean(axis=(2, 4))
        thumbnail = thumbnail.repeat(2, axis=1).repeat(2, axis=2)
        np.testing.assert_allclose(data["low"][:, :192], thumbnail.reshape(-1, 192))
        self.assertTrue(np.all((image >= 0) & (image <= 1)))

    def test_source_stream_is_stable_and_manifest_binds_observed_bytes(self):
        first = dataset("validation", self.profile)
        second = dataset("validation", copy.deepcopy(self.profile))
        self.assertEqual(manifest(first), manifest(second))
        np.testing.assert_array_equal(first["full"], second["full"])
        changed = copy.deepcopy(self.profile)
        changed["instructions_per_source"] = 6
        other = dataset("validation", changed)
        self.assertEqual(first["sources"], other["sources"])
        self.assertNotEqual(manifest(first)["inputs_sha256"], manifest(other)["inputs_sha256"])

    def test_test_construction_is_rejected_before_any_random_generation(self):
        with patch("data_v2.np.random.default_rng", side_effect=AssertionError("must stay sealed")):
            with self.assertRaisesRegex(ValueError, "test split sealed"):
                dataset("test", self.profile)

    def test_duplicate_split_seed_and_out_of_bounds_profile_reject(self):
        repeated = copy.deepcopy(self.profile)
        repeated["seeds"]["validation"] = repeated["seeds"]["train"]
        with self.assertRaisesRegex(ValueError, "different source seeds"):
            dataset("train", repeated)
        for key, value in (("instructions_per_source", 37), ("variants", True),
                           ("noise_range", [0.0, float("nan")]), ("vertical_shifts", [2])):
            profile = copy.deepcopy(self.profile)
            profile[key] = value
            with self.assertRaises(ValueError):
                dataset("validation", profile)
        oversized = copy.deepcopy(self.profile)
        oversized["sources_per_class"]["train"] = 256
        oversized["instructions_per_source"] = 36
        oversized["variants"] = 64
        with self.assertRaisesRegex(ValueError, "bounded model batch"):
            dataset("train", oversized)


if __name__ == "__main__":
    unittest.main()
