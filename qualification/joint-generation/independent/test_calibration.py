import hashlib
import unittest

import numpy as np

from independent.calibration import calibration_manifest, stratified_indices


def metadata_grid(sources_per_class=16):
    data = {"split": "train", "labels": [], "source_scenes": [], "source_ids": [], "input_hashes": []}
    for scene in range(12):
        for source in range(sources_per_class):
            identity = hashlib.sha256(f"physical:{scene}:{source}".encode()).hexdigest()
            for target in range(12):
                for variant in range(2):
                    data["labels"].append(target)
                    data["source_scenes"].append(scene)
                    data["source_ids"].append("physical-v2:" + identity)
                    data["input_hashes"].append(hashlib.sha256(f"input:{identity}:{target}:{variant}".encode()).hexdigest())
    data["labels"] = np.asarray(data["labels"])
    data["source_scenes"] = np.asarray(data["source_scenes"])
    return data


def reordered(data, indices):
    return {"split": data["split"], "labels": data["labels"][indices],
            "source_scenes": data["source_scenes"][indices],
            "source_ids": [data["source_ids"][index] for index in indices],
            "input_hashes": [data["input_hashes"][index] for index in indices]}


class CalibrationTests(unittest.TestCase):
    def test_both_class_margins_and_physical_sources_are_balanced(self):
        data = metadata_grid()
        indices = stratified_indices(data)
        report = calibration_manifest(data, indices)
        self.assertEqual(indices.shape, (72,))
        self.assertEqual(report["source_class_counts"], {str(value): 6 for value in range(12)})
        self.assertEqual(report["target_class_counts"], {str(value): 6 for value in range(12)})
        self.assertEqual((report["physical_source_count"], set(report["source_counts"].values())), (72, {1}))
        self.assertEqual(set(data["source_scenes"][indices[:64]]), set(range(12)))
        np.testing.assert_array_equal(data["labels"][indices], np.tile(np.arange(12), 6))
        for index in indices:
            rows = [row for row, source in enumerate(data["source_ids"])
                    if source == data["source_ids"][index] and data["labels"][row] == data["labels"][index]]
            self.assertEqual(data["input_hashes"][index], min(data["input_hashes"][row] for row in rows))

    def test_shuffle_preserves_selected_identities_and_interleaving(self):
        data = metadata_grid()
        original = calibration_manifest(data, stratified_indices(data))
        permutation = np.random.default_rng(77113).permutation(len(data["labels"]))
        shuffled = reordered(data, permutation)
        selected = calibration_manifest(shuffled, stratified_indices(shuffled))
        self.assertEqual({key: value for key, value in original.items() if key != "indices"},
                         {key: value for key, value in selected.items() if key != "indices"})

    def test_matching_handles_competing_targets_without_reusing_sources(self):
        data = metadata_grid(3)
        keep = []
        for index, (scene, target, source) in enumerate(zip(data["source_scenes"], data["labels"], data["source_ids"])):
            source_ids = sorted(set(value for value, owner in zip(data["source_ids"], data["source_scenes"]) if owner == scene))
            offset = (int(scene) - int(target)) % 12
            if offset in (0, 1, 2) and (source in source_ids[:2] if offset == 0 else source in (source_ids[0], source_ids[2])):
                keep.append(index)
        subset = reordered(data, np.asarray(keep))
        report = calibration_manifest(subset, stratified_indices(subset, per_class=3))
        self.assertEqual(report["physical_source_count"], 36)
        self.assertEqual(report["target_class_counts"], {str(value): 3 for value in range(12)})

    def test_missing_classes_sources_and_target_pairs_fail_without_fallback(self):
        data = metadata_grid()
        with self.assertRaisesRegex(ValueError, "source class 11"):
            stratified_indices(reordered(data, np.flatnonzero(data["source_scenes"] != 11)))
        with self.assertRaisesRegex(ValueError, "distinct sources"):
            stratified_indices(metadata_grid(5))
        keep = ~((data["source_scenes"] == 0) & (data["labels"] == 7))
        with self.assertRaisesRegex(ValueError, "matching failed"):
            stratified_indices(reordered(data, np.flatnonzero(keep)))

    def test_nontraining_metadata_is_rejected_before_reading_columns(self):
        for split in ("validation", "test"):
            with self.assertRaisesRegex(ValueError, "train-only"):
                stratified_indices({"split": split})
        data = metadata_grid()
        del data["split"]
        self.assertEqual(len(stratified_indices(data)), 72)


if __name__ == "__main__":
    unittest.main()
