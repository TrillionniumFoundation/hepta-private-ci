import hashlib
import unittest
from unittest.mock import patch

import numpy as np

from independent.calibration import calibration_manifest, global_balanced_indices, stratified_indices


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


def metadata_graph(targets):
    """Six manual physical sources per class, two rows per available edge."""
    data = {"split": "train", "labels": [], "source_scenes": [], "source_ids": [], "input_hashes": []}
    for scene in range(12):
        for source in range(6):
            identity = f"hand-source:{scene}:{source}"
            for target in targets(scene):
                for variant in range(2):
                    data["labels"].append(target)
                    data["source_scenes"].append(scene)
                    data["source_ids"].append(identity)
                    data["input_hashes"].append(hashlib.sha256(
                        f"hand-input:{identity}:{target}:{variant}".encode()).hexdigest())
    data["labels"], data["source_scenes"] = np.asarray(data["labels"]), np.asarray(data["source_scenes"])
    return data


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


class GlobalCalibrationTests(unittest.TestCase):
    def assert_balanced(self, data, indices):
        report = calibration_manifest(data, indices)
        self.assertEqual(indices.shape, (72,))
        self.assertEqual(report["source_class_counts"], {str(i): 6 for i in range(12)})
        self.assertEqual(report["target_class_counts"], {str(i): 6 for i in range(12)})
        self.assertEqual((report["physical_source_count"], set(report["source_counts"].values())), (72, {1}))
        np.testing.assert_array_equal(data["labels"][indices], np.tile(np.arange(12), 6))
        for round_ in range(6):
            self.assertEqual(set(data["source_scenes"][indices[round_ * 12:(round_ + 1) * 12]]), set(range(12)))
        for row in indices:
            choices = [data["input_hashes"][i] for i in range(len(data["labels"]))
                       if data["source_ids"][i] == data["source_ids"][row]
                       and data["labels"][i] == data["labels"][row]]
            self.assertEqual(data["input_hashes"][row], min(choices))
        return report

    def test_cyclic_joint_cell_can_be_missing_while_both_margins_are_feasible(self):
        data = metadata_graph(lambda scene: [scene])
        with self.assertRaisesRegex(ValueError, "matching failed"):
            stratified_indices(data)
        self.assert_balanced(data, global_balanced_indices(data))

    def test_competing_target_capacity_requires_the_global_assignment(self):
        data = metadata_graph(lambda scene: [0, 1] if scene == 0 else ([0] if scene == 1 else [scene]))
        indices = global_balanced_indices(data, salt="hand-global-competition-v1")
        self.assert_balanced(data, indices)
        self.assertEqual(set(data["source_scenes"][indices[data["labels"][indices] == 0]]), {1})
        self.assertEqual(set(data["source_scenes"][indices[data["labels"][indices] == 1]]), {0})

    def test_global_hall_infeasibility_remains_an_explicit_failure(self):
        data = metadata_graph(lambda scene: [0] if scene in (0, 1)
                              else (list(range(1, 12)) if scene == 2 else [scene]))
        self.assertEqual(set(data["labels"]), set(range(12)))
        with self.assertRaisesRegex(ValueError, "global.*infeasible"):
            global_balanced_indices(data)
        with self.assertRaisesRegex(ValueError, "distinct sources"):
            global_balanced_indices(metadata_grid(5))
        with self.assertRaisesRegex(ValueError, "train-only"):
            global_balanced_indices({"split": "test"})

    def test_shuffle_preserves_all_selected_identities_and_each_round(self):
        data = metadata_grid(8)
        original = self.assert_balanced(data, global_balanced_indices(data, salt="hand-global-shuffle-v1"))
        shuffled = reordered(data, np.random.default_rng(2108).permutation(len(data["labels"])))
        actual = self.assert_balanced(shuffled, global_balanced_indices(shuffled, salt="hand-global-shuffle-v1"))
        self.assertEqual({key: value for key, value in original.items() if key != "indices"},
                         {key: value for key, value in actual.items() if key != "indices"})

    def test_runner_dispatch_is_explicit_core_only_and_preserves_default(self):
        from independent import run
        plan = {"calibration_per_class": 6, "calibration_salt": "hand-dispatch"}
        data, selected = {"manual": True}, np.array([3, 4])
        with patch.object(run, "stratified_indices", return_value=selected) as cyclic, \
             patch.object(run, "global_balanced_indices", side_effect=AssertionError("unused global")):
            self.assertIs(run.calibration_indices(data, plan), selected)
            cyclic.assert_called_once_with(data, 6, "hand-dispatch")
        with patch.object(run, "stratified_indices", side_effect=AssertionError("unused cyclic")), \
             patch.object(run, "global_balanced_indices", return_value=selected) as global_match:
            core = {**plan, "experiment_id": "core-c1", "calibration_matching": "global-balanced-margins-v1"}
            self.assertIs(run.calibration_indices(data, core), selected)
            global_match.assert_called_once_with(data, 6, "hand-dispatch")
            for change in ({"experiment_id": "efficient-r2"}, {"calibration_matching": None},
                           {"calibration_matching": "unknown"}):
                with self.subTest(change=change), self.assertRaisesRegex(ValueError, "unsupported"):
                    run.calibration_indices(data, {**core, **change})


if __name__ == "__main__":
    unittest.main()
