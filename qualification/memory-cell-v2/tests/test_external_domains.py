"""Source integrity, train-only fitting, strong baselines and saved read pipeline."""

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from v2.external_domains import (
    DEFAULT_PROFILE,
    Standardizer,
    _row_key,
    _run_case,
    build_external_tasks,
    exact_index,
    exact_predict,
    neighbors_predict,
    select_k,
    stratified_group_split,
)


class ExternalDomainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tasks = build_external_tasks(seed=8001)

    def test_source_labels_and_feature_groups_are_partitioned_without_overlap(self):
        for task in self.tasks.values():
            ids = list(task.indices.values())
            np.testing.assert_array_equal(
                np.sort(np.concatenate(ids)), np.arange(len(task.X))
            )
            keys = [{_row_key(task.X[i]) for i in rows} for rows in ids]
            self.assertFalse(
                keys[0] & keys[1] or keys[0] & keys[2] or keys[1] & keys[2]
            )
            for rows in ids:
                self.assertEqual(set(task.y[rows]), set(task.source["classes"]))
            self.assertEqual(task.source["dataset_license"], "CC-BY-4.0")
            self.assertFalse(task.source["patient_data"])

    def test_normalizer_uses_only_training_statistics_and_a_common_65d_contract(self):
        for task in self.tasks.values():
            train = task.X[task.indices["train"]]
            np.testing.assert_allclose(task.normalizer.mean, train.mean(axis=0))
            expected_scale = train.std(axis=0)
            np.testing.assert_allclose(
                task.normalizer.scale, np.where(expected_scale == 0, 1, expected_scale)
            )
            transformed = task.normalizer.transform(task.X[task.indices["test"]])
            self.assertEqual(transformed.shape, (len(task.indices["test"]), 65))
            np.testing.assert_array_equal(transformed[:, 64], 1)
            np.testing.assert_array_equal(transformed[:, task.X.shape[1] : 64], 0)
            restored = Standardizer.from_manifest(task.normalizer.manifest())
            np.testing.assert_array_equal(
                restored.transform(train), task.normalizer.transform(train)
            )

    def test_exact_recovery_and_unseen_abstention_remain_separate(self):
        for task in self.tasks.values():
            train, test = task.indices["train"], task.indices["test"]
            index = exact_index(task.X[train], task.y[train])
            self.assertEqual(
                exact_predict(index, task.X[train]), task.y[train].tolist()
            )
            self.assertEqual(exact_predict(index, task.X[test]), [None] * len(test))

    def test_knn_is_an_actual_nearest_neighbor_baseline_with_deterministic_ties(self):
        X = np.array([[-1.0], [1.0], [-2.0], [2.0], [3.0]])
        y = np.array([2, 0, 0, 1, 1])
        self.assertEqual(neighbors_predict(X, y, np.array([[0.0]]), 1, 3), [2])
        self.assertEqual(neighbors_predict(X, y, np.array([[0.0]]), 5, 3), [0])
        chosen, scores = select_k(np.array([0, 1, 1]), {1: [0, 0, 1], 5: [0, 1, 1]})
        self.assertEqual(chosen, 5)
        self.assertGreater(scores[5], scores[1])
        self.assertEqual(select_k(np.array([0]), {1: [0], 5: [0]})[0], 1)

    def test_same_feature_groups_cannot_leak_when_a_duplicate_has_conflicting_labels(
        self,
    ):
        with self.assertRaisesRegex(ValueError, "conflicting labels"):
            stratified_group_split(np.array([[1.0], [1.0]]), np.array([0, 1]), 8001)

    def test_second_development_split_changes_assignment_without_changing_sources(self):
        second = build_external_tasks(seed=8003)
        for name, first in self.tasks.items():
            other = second[name]
            self.assertEqual(first.source, other.source)
            np.testing.assert_array_equal(first.X, other.X)
            np.testing.assert_array_equal(first.y, other.y)
            self.assertFalse(
                np.array_equal(first.indices["test"], other.indices["test"])
            )

    def test_development_pipeline_reloads_and_charges_actual_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "iris"
            result = _run_case(
                self.tasks["iris"],
                {**DEFAULT_PROFILE, "steps": 2},
                directory,
                "0" * 40,
                8001,
            )
            self.assertTrue(result["model_reload_parity"])
            self.assertEqual(
                result["scores"]["written_recovery"]["exact"]["known_accuracy"], 1.0
            )
            self.assertEqual(result["scores"]["unseen_test"]["exact"]["coverage"], 0.0)
            for name, count in result["costs"]["stored_components_bytes"].items():
                self.assertEqual(count, (directory / name).stat().st_size)
            selection = json.loads((directory / "selection.json").read_text())
            self.assertEqual(result["selected_k"], selection["selected_k"])
            self.assertFalse(selection["test_targets_used"])
            expected = result["costs"]["model_artifact_bytes"] + sum(
                result["costs"]["stored_components_bytes"][name]
                for name in ("normalizer.json", "labels.json", "written-records.npz")
            )
            self.assertEqual(
                result["costs"]["deployment_bytes"]["model_with_replay"], expected
            )


if __name__ == "__main__":
    unittest.main()
