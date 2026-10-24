import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from analyze_calibrated_pairs import METRICS, analyze_pair, load_cases, metric_vectors, paired_bootstrap
from cell_calibration_v2 import discrimination_metrics
from cell_calibrated_curve import inventory, write_json
from cell_calibrated_evaluate import _record
from cell_learning_metrics import task_metrics


class PairedAnalysisTests(unittest.TestCase):
    def cases(self, quality=.9, seeds=(7, 17, 29)):
        y = np.tile([0, 1], 4)
        p = np.array([[quality, 1-quality] if k == 0 else [1-quality, quality] for k in y])
        return {("task", s): dict(task="task", seed=s, family="family", labels=y,
            probabilities=p.copy(), prior_threshold=.5, source_ids=tuple(map(str, range(8))),
            group_ids=tuple(f"bug-{i//2}" for i in range(8))) for s in seeds}

    def compare(self, left, right, seeds=(7, 17, 29)):
        return paired_bootstrap(left, right, seeds=seeds, declared_tasks=["task"],
                                families={"task": "family"}, draws=200, seed=20261024)

    def test_identical_models_have_exactly_zero_paired_intervals(self):
        cases = self.cases()
        report, counts, groups = self.compare(cases, cases)
        self.assertEqual(len(groups), 4)
        np.testing.assert_array_equal(counts.sum(axis=1), np.full(200, 4))
        for metric in METRICS:
            result = report["families"][0]["metrics"][metric]
            self.assertEqual(result["difference_left_minus_right"], 0.)
            self.assertEqual(result["ci95_percentile"], [0., 0.])

    def test_known_improvement_and_nll_sign(self):
        report, _, _ = self.compare(self.cases(.9), self.cases(.5))
        metrics = report["families"][0]["metrics"]
        self.assertEqual(metrics["balanced_accuracy"]["ci95_percentile"], [.5, .5])
        self.assertEqual(metrics["auroc"]["ci95_percentile"], [.5, .5])
        self.assertLess(metrics["nll"]["ci95_percentile"][1], -.5)
        self.assertEqual(metrics["balanced_accuracy"]["valid_bootstrap_draws"], 200)

    def test_seeds_are_scored_before_averaging_not_ensembled(self):
        left = self.cases(.51, seeds=(7, 17))
        left[("task", 17)]["probabilities"] = self.cases(.01)[("task", 7)]["probabilities"]
        report, _, _ = self.compare(left, self.cases(.5, seeds=(7, 17)), seeds=(7, 17))
        result = report["families"][0]["metrics"]["balanced_accuracy"]
        self.assertEqual(result["left"], .5)
        self.assertEqual(result["difference_left_minus_right"], 0.)

    def test_weighted_auc_and_metrics_equal_literal_cluster_replication(self):
        case = self.cases()[('task', 7)]
        case["probabilities"] = np.array([[.8,.2],[.2,.8],[.6,.4],[.6,.4],
                                           [.1,.9],[.9,.1],[.5,.5],[.5,.5]])
        counts = np.array([[0, 2, 1, 1], [4, 0, 0, 0]])
        groups = {f"bug-{i}": i for i in range(4)}
        result = metric_vectors(case, counts, groups)
        for row, multiplicities in enumerate(counts):
            ids = np.repeat(np.arange(8), np.repeat(multiplicities, 2))
            y, p = case["labels"][ids], case["probabilities"][ids]
            m, d = task_metrics(p, y), discrimination_metrics(p, y, [.5,.5])
            expected = [m["balanced_accuracy"], m["nll"], d["auroc"], d["balanced_accuracy_at_prior_threshold"]]
            np.testing.assert_allclose(result[row], expected, atol=1e-12, rtol=1e-12)

    def test_mismatched_labels_rejected_and_missing_seed_explicit(self):
        left, right = self.cases(), self.cases()
        right[("task", 7)]["labels"] = 1-right[("task", 7)]["labels"]
        with self.assertRaises(ValueError):
            self.compare(left, right)
        right = self.cases()
        right[("task", 7)]["training_source_ids"] = ("different",)
        with self.assertRaises(ValueError):
            self.compare(left, right)
        right = self.cases(); del right[("task", 17)]
        result, counts, groups = self.compare(left, right)
        self.assertEqual(result["status"], "not_evaluable")
        self.assertEqual(result["unavailable_tasks"][0]["task"], "task")
        self.assertEqual(counts.shape, (200, 0))
        self.assertEqual(groups, [])

    def test_sealed_raw_artifact_roundtrip_and_mutation_rejection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); study = root/"study"; study.mkdir()
            plan = {"tasks": ["task"], "families": {"task": "family"}, "dataset_sha256": "fixture",
                    "protocol": {"seeds": [7,17,29]}, "holdout_use": "fixture"}
            write_json(study/"study-plan.json", plan)
            write_json(study/"summary.json", {"tasks_evaluated": ["task"]})
            evaluation = study/"task/evaluation"; evaluation.mkdir(parents=True)
            case = self.cases()[("task", 7)]
            report = {"plan": {"family_id": "family"}, "labels": case["labels"].tolist(),
                      "source_ids": list(case["source_ids"]), "group_ids": list(case["group_ids"]), "runs": []}
            for s in (7,17,29):
                location = evaluation/f"seed-{s}_n-128"; location.mkdir()
                arm = _record(location, "gated", np.log(case["probabilities"]), case["probabilities"],
                              case["labels"], np.ones(8, dtype=bool), [.5,.5], .7)
                report["runs"].append({"seed": s, "budget": 128, "directory": location.name,
                                       "selected_arm": "gated", "arms": {"gated": arm}})
            write_json(evaluation/"report.json", report)
            write_json(evaluation/"seal.json", {"schema": "hepta.calibrated-evaluation-seal.v1", "files": inventory(evaluation)})
            result = analyze_pair(study, study, left_arm="gated", right_arm="selected", output=root/"analysis", draws=200)
            self.assertEqual(result["families"][0]["metrics"]["auroc"]["ci95_percentile"], [0.,0.])
            (evaluation/"seed-7_n-128/gated.npz").write_bytes(b"changed")
            with self.assertRaises(ValueError):
                load_cases(study, "gated", 128)


if __name__ == "__main__":
    unittest.main()
