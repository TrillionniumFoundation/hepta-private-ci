import json
import hashlib
import tempfile
import unittest
from pathlib import Path

import numpy as np

from cell_calibrated_curve import prepare_curve, sha_file, verify_prepared
from cell_calibrated_evaluate import _record, evaluate_curve
from cell_learning_curve import Cohort


class CalibratedCurveTests(unittest.TestCase):
    def cohort(self, split, count=24):
        seed = {"train": 1, "calibration": 2, "holdout": 3}[split]
        rng = np.random.default_rng(seed)
        y = np.tile([0, 1], count//2)
        x = rng.normal(size=(count, 4)); x[:, 0] += (2*y-1)*2
        rows = tuple(dict(source_id=f"{split}-{i}", group_id=f"g-{split}-{i}",
                          text=f"{split} unique source content number {i}") for i in range(count))
        return Cohort(x, y, rows, split)

    def plan(self):
        return {"budgets": [8], "seeds": [7], "l2_grid": [.1, 1.], "checkpoints": [2, 4], "rank": 2}

    def test_complete_prepare_freeze_score_and_fresh_process(self):
        with tempfile.TemporaryDirectory() as directory:
            prepared, evaluation = Path(directory)/"prepared", Path(directory)/"evaluation"
            freeze = prepare_curve(self.cohort("train"), self.cohort("calibration"),
                feature_identity="fixture-v2", output_dir=prepared, task_id="binary-task", protocol=self.plan())
            before = sha_file(prepared/"seal.json")
            self.assertFalse(freeze["plan"]["holdout_supplied_to_preparation"])
            run = freeze["runs"][0]
            self.assertEqual(run["training_class_counts"], [4, 4])
            self.assertEqual(len(set(run["training_group_ids"])), 8)
            self.assertEqual(len(run["search_paths"]), 6)
            report = evaluate_curve(self.cohort("holdout"), feature_identity="fixture-v2",
                prepared_dir=prepared, output_dir=evaluation, holdout_use="fixture")
            self.assertEqual(set(report["runs"][0]["arms"]),
                {"prior_only", "exact", "bm25", "dense_nearest", "prototype", "linear", "gated", "residual"})
            for mode in ("linear", "gated", "residual"):
                arm = report["runs"][0]["arms"][mode]
                self.assertTrue(arm["fresh_process"]["bitwise_equal_logits_and_probabilities"])
                self.assertFalse(arm["fresh_process"]["test_labels_provided_to_child"])
                self.assertEqual(set(arm["controls"]), {"parameters_off", "shuffled_parameters"})
            self.assertEqual(before, sha_file(prepared/"seal.json"))
            self.assertEqual(verify_prepared(prepared), freeze)
            with self.assertRaises(FileExistsError):
                evaluate_curve(self.cohort("holdout"), feature_identity="fixture-v2",
                    prepared_dir=prepared, output_dir=evaluation, holdout_use="fixture")

    def test_budget_unavailable_without_replication(self):
        with tempfile.TemporaryDirectory() as directory:
            plan = self.plan(); plan["budgets"] = [128]
            frozen = prepare_curve(self.cohort("train"), self.cohort("calibration"),
                feature_identity="id", output_dir=Path(directory)/"prepared", task_id="t", protocol=plan)
            self.assertEqual(frozen["runs"], [])
            self.assertEqual(frozen["unavailable"][0]["selected_unique_groups"], 24)
            self.assertEqual(frozen["unavailable"][0]["budget"], 128)

    def test_overlap_and_identity_fail_before_scoring(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            train, calibration = self.cohort("train"), self.cohort("calibration")
            rows = list(calibration.rows); rows[0] = dict(rows[0], group_id=train.rows[0]["group_id"])
            bad = Cohort(calibration.features, calibration.labels, tuple(rows), "calibration")
            with self.assertRaises(ValueError):
                prepare_curve(train, bad, feature_identity="id", output_dir=root/"bad", task_id="t", protocol=self.plan())
            self.assertFalse((root/"bad").exists())
            prepare_curve(train, calibration, feature_identity="id", output_dir=root/"prepared", task_id="t", protocol=self.plan())
            with self.assertRaises(ValueError):
                evaluate_curve(self.cohort("holdout"), feature_identity="wrong",
                    prepared_dir=root/"prepared", output_dir=root/"evaluation", holdout_use="fixture")
            self.assertFalse((root/"evaluation").exists())

    def test_unsealed_or_mutated_preparation_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)/"prepared"
            plan = self.plan(); plan["budgets"] = [128]
            prepare_curve(self.cohort("train"), self.cohort("calibration"),
                feature_identity="id", output_dir=root, task_id="t", protocol=plan)
            (root/"unexpected.json").write_text("{}")
            with self.assertRaises(ValueError):
                verify_prepared(root)
            (root/"unexpected.json").unlink()
            state = json.loads((root/"frozen.json").read_text()); state["authority"] = "changed"
            (root/"frozen.json").write_text(json.dumps(state))
            with self.assertRaises(ValueError):
                verify_prepared(root)

    def test_media_identity_permits_neutral_text_and_rejects_content_overlap(self):
        cohorts = [self.cohort(s) for s in ("train", "calibration", "holdout")]
        cohorts = [Cohort(c.features, c.labels, tuple(dict(r, text="neutral media input") for r in c.rows), c.split)
                   for c in cohorts]
        identity = {r["source_id"]: hashlib.sha256(r["source_id"].encode()).hexdigest() for c in cohorts for r in c.rows}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                prepare_curve(*cohorts[:2], feature_identity="id", output_dir=root/"text", task_id="t", protocol=self.plan())
            prepare_curve(*cohorts[:2], feature_identity="id", output_dir=root/"media", task_id="t", protocol=self.plan(),
                          input_modality="image", input_content_sha256=identity)
            collision = dict(identity)
            collision[cohorts[2].rows[0]["source_id"]] = identity[cohorts[0].rows[0]["source_id"]]
            with self.assertRaises(ValueError):
                evaluate_curve(cohorts[2], feature_identity="id", prepared_dir=root/"media", output_dir=root/"bad",
                    holdout_use="fixture", input_modality="image", input_content_sha256=collision)
            report = evaluate_curve(cohorts[2], feature_identity="id", prepared_dir=root/"media", output_dir=root/"good",
                holdout_use="fixture", input_modality="image", input_content_sha256=identity)
            self.assertFalse(report["runs"][0]["arms"]["bm25"]["modality_appropriate"])
            self.assertTrue(report["runs"][0]["arms"]["prototype"]["modality_appropriate"])

    def test_absent_heldout_class_does_not_become_perfect_balanced_accuracy(self):
        with tempfile.TemporaryDirectory() as directory:
            p = np.tile([.1, .9], (5, 1))
            result = _record(Path(directory), "one-class", np.log(p), p,
                np.ones(5, dtype=int), np.ones(5, dtype=bool), [.2, .8], .7)
            self.assertIsNone(result["semantic"]["balanced_accuracy"])
            self.assertEqual(result["semantic"]["forced_accuracy"], 1.)
            self.assertEqual(result["semantic"]["balanced_accuracy_status"], "unavailable_missing_holdout_class")
            self.assertIsNone(result["secondary_discrimination"]["auroc"])


if __name__ == "__main__":
    unittest.main()
