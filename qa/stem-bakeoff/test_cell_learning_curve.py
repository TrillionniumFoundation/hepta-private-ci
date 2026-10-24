"""Mechanism fixtures, not empirical evidence about real task quality."""

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from cell_learning_curve import Cohort, run_curve, training_order, validate_cohorts


def cohort(split, count=16, invert=False):
    y = np.arange(count) % 2
    x = np.column_stack((2 * y - 1, np.ones(count), np.linspace(-0.2, 0.2, count)))
    rows = [{"source_id": f"{split}/{i}", "group_id": f"event/{split}/{i}",
             "text": f"{split} source {i}: {'parser' if label else 'network'} diagnostic"}
            for i, label in enumerate(y)]
    return Cohort(x, 1 - y if invert else y, rows, split)


class LearningCurveTests(unittest.TestCase):
    def test_source_group_and_normalized_text_overlap_reject(self):
        train, cal, test = cohort("train"), cohort("calibration"), cohort("holdout")
        validate_cohorts(train, cal, test, 2)
        for key in ("source_id", "group_id", "text"):
            rows = [dict(row) for row in test.rows]
            rows[0][key] = train.rows[0][key]
            if key == "text":
                rows[0][key] = "  " + rows[0][key].upper() + "  "
            with self.assertRaisesRegex(ValueError, "cross-split overlap"):
                validate_cohorts(train, cal, Cohort(test.features, test.labels, rows, "holdout"), 2)

    def test_labels_and_outcomes_cannot_be_query_fields(self):
        current = cohort("train")
        rows = [dict(row) for row in current.rows]
        rows[0]["outcome"] = 1
        with self.assertRaisesRegex(ValueError, "only source_id"):
            Cohort(current.features, current.labels, rows, "train")
        with self.assertRaises(ValueError):
            Cohort(current.features, current.labels.astype(bool), current.rows, "train")

    def test_training_order_balances_and_counts_distinct_groups(self):
        current = cohort("train")
        order = training_order(current, 2, 7)
        self.assertEqual(order, training_order(current, 2, 7))
        self.assertEqual(np.bincount(current.labels[order[:8]]).tolist(), [4, 4])
        rows = [dict(row) for row in current.rows]
        rows[2]["group_id"] = rows[0]["group_id"]
        changed = Cohort(current.features, current.labels, rows, "train")
        selected = training_order(changed, 2, 7)
        self.assertEqual(len(selected), 15)
        self.assertEqual(len({changed.rows[i]["group_id"] for i in selected}), 15)

    def test_real_training_fresh_process_and_no_test_label_feedback(self):
        train, cal, test = cohort("train"), cohort("calibration"), cohort("holdout")
        with tempfile.TemporaryDirectory() as directory:
            results = []
            for index, target in enumerate((test, cohort("holdout", invert=True))):
                results.append(run_curve(train, cal, target, classes=2, feature_identity={"encoder": "fixture"},
                    output_dir=Path(directory) / str(index), budgets=(8, 32), seeds=(7,), steps=15, rank=2))
            for result in results:
                self.assertEqual(result["status"], "partial_budgets_unavailable")
                self.assertEqual(len(result["unavailable"]), 1)
                run = result["runs"][0]
                self.assertEqual(len(set(run["training_source_ids"])), 8)
                self.assertEqual(run["arms"]["exact"]["semantic"]["coverage"], 0)
                for mode in ("linear", "gated", "residual"):
                    arm = run["arms"][mode]
                    self.assertTrue(arm["fresh_process"]["matched"])
                    self.assertFalse(arm["fresh_process"]["test_labels_provided_to_child"])
                    self.assertEqual(arm["training"]["example_updates"], 120)
                    self.assertEqual(arm["controls"]["parameters_off"]["semantic"]["overall_success"], 0)
                    self.assertNotEqual(arm["training"]["trained_tensor_sha256"],
                                        arm["controls"]["shuffled_parameters"]["tensor_sha256"])
            for mode in ("linear", "gated", "residual"):
                left, right = [result["runs"][0]["arms"][mode] for result in results]
                self.assertEqual(left["logits"], right["logits"])
                self.assertEqual(left["temperature"], right["temperature"])
                self.assertEqual(left["training"]["trained_tensor_sha256"],
                                 right["training"]["trained_tensor_sha256"])
            persisted = json.loads((Path(directory) / "0/report.json").read_bytes())
            self.assertEqual(persisted["plan"]["winner_selection"], "none")


if __name__ == "__main__":
    unittest.main()
