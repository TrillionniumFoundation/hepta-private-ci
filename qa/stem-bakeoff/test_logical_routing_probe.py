"""Retain historical selection, separate relevance, and preserve source outputs."""

import copy
from pathlib import Path
import tempfile
import unittest

import numpy as np

from cell_batch_runtime import BatchedCellRuntime
from cell_learning_models import NumpyCellHead
from logical_routing_probe import measure_routing, run_probe

IDENTITY = "a" * 64
SOURCES = ("b" * 64, "c" * 64)


class LogicalRoutingProbeTests(unittest.TestCase):
    def fixture(self):
        train = np.random.default_rng(3).normal(size=(16, 4))
        heads, tasks = [], [f"task-{i}" for i in range(32)]
        for index in range(32):
            head = NumpyCellHead(4, 2, "gated", seed=index)
            head.train(train, (train[:, index % 4] > 0).astype(int), steps=3)
            head.feature_identity = IDENTITY
            heads.append(head)
        keys = np.random.default_rng(7).normal(size=(32, 4))
        x = np.random.default_rng(11).normal(size=(2, 4))
        original = {"results": []}
        for count in (64, 256):
            indices = np.arange(count) % 32
            runtime = BatchedCellRuntime([heads[i] for i in indices],
                [f"cell-{i:06d}" for i in range(count)], [tasks[i] for i in indices],
                IDENTITY, router_keys=keys[indices])
            output = runtime.predict(x, source_digests=SOURCES, feature_identity=IDENTITY,
                                     generation=1, top_k=16)
            original["results"].append({"resident_cells": count, "measurements": {"selective": {
                "top_k": 16, "selected_cell_ids": output["selected_cell_ids"],
                "retained_original_marker": "unchanged"}}})
        return heads, tasks, x, keys, original

    def test_comparison_preserves_history_and_exact_scatter_without_relevance_inputs(self):
        heads, tasks, x, keys, original = self.fixture()
        before = copy.deepcopy(original)
        results, arrays = measure_routing(heads, tasks, x, SOURCES, IDENTITY, keys, original, repeats=5)
        self.assertEqual(original, before)
        for result in results:
            self.assertTrue(result["scatter_bitwise_matches_physical_all"])
            self.assertTrue(result["scalar_class_predictions_match"])
            self.assertLess(result["scalar_max_abs_error"], 1e-9)
            self.assertEqual(result["retained_private_head_states"], 32)
            count = result["physical_cell_ids"]
            self.assertEqual(arrays[f"cells{count}_all_unique_fanout_logits"].shape, (2, count, 2))
            np.testing.assert_array_equal(arrays[f"cells{count}_physical_all_logits"],
                                          arrays[f"cells{count}_all_unique_fanout_logits"])
            self.assertEqual(result["measurements"]["physical_all"]["measured_head_evaluations"],
                             5 * 2 * count)
            for name, states in (("unique_top16", 16), ("all_unique_fanout", 32)):
                measured = result["measurements"][name]
                self.assertEqual(measured["measured_head_evaluations"], 5 * 2 * states)
                self.assertEqual(measured["computed_states_per_row"], states)
                self.assertEqual(measured["encoder_invocations"], 0)
                self.assertEqual(measured["private_parameter_updates"], 0)
                self.assertEqual(len(measured["selected_task_ids"][0]), states)
                self.assertNotIn("mean_positive_task_recall", measured)
                self.assertEqual(measured["timing"]["total_wall"]["sample_count"], 5)

    def test_changed_historical_selection_rejects_instead_of_rewriting_it(self):
        heads, tasks, x, keys, original = self.fixture()
        original["results"][0]["measurements"]["selective"]["selected_cell_ids"][0][0] = "changed"
        with self.assertRaisesRegex(ValueError, "not reproduced"):
            measure_routing(heads, tasks, x, SOURCES, IDENTITY, keys, original, repeats=5)

    def test_probe_cannot_write_into_original_study_or_feature_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for target in (root / "study", root / "features" / "new"):
                with self.assertRaisesRegex(ValueError, "must not modify"):
                    run_probe(root / "missing.json", root / "features", root / "study", target)
            self.assertEqual(list(root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
