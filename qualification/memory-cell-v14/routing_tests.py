"""Behavioral checks; synthetic vectors here are not semantic experiment evidence."""

import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from routing import CalibratedExperts, RoutingCalibration, choose_candidate, crossfit


ROOT = Path(__file__).resolve().parent


class CountingExpert:
    def __init__(self):
        self.params = {"W": np.array([[1., -1.], [0., 0.]]), "b": np.zeros(2)}
        self.rows = 0

    def features(self, X):
        self.rows += len(X)
        return X


class RoutingTests(unittest.TestCase):
    def test_serving_executes_only_selected_experts_and_normalizes(self):
        experts = [CountingExpert() for _ in range(3)]
        network = SimpleNamespace(partition=[[0, 1], [2, 3], [4, 5]], num_classes=6,
                                  router=np.array([[0., 0., 0.], [0., 0., 0.], [3., 2., -4.]]),
                                  top_k=2, experts=experts)
        model = CalibratedExperts(network)
        result = model.predict_proba(np.array([[1., 0.], [-1., 0.]]))
        np.testing.assert_allclose(result.sum(axis=1), np.ones(2))
        np.testing.assert_array_equal(result[:, 4:], np.zeros((2, 2)))
        self.assertEqual(([e.rows for e in experts], model.stats),
                         ([2, 2, 0], {"requests": 2, "expert_example_invocations": 4}))

    def test_fit_reduces_overconfidence_on_calibration_without_mutating_experts(self):
        calibration = RoutingCalibration([[0], [1]])
        route = np.tile(np.array([[6., -6.]]), (12, 1))
        labels = np.array([0] * 7 + [1] * 5)
        expert = [np.zeros((12, 1)), np.zeros((12, 1))]
        receipt = calibration.fit(route, expert, labels)
        self.assertEqual(receipt["status"], "fitted")
        self.assertLess(receipt["final_regularized_nll"], receipt["initial_regularized_nll"])
        self.assertGreater(np.exp(calibration.route(route))[0, 1], .1)

    def test_crossfit_keeps_each_scored_fold_out_of_fit(self):
        network = SimpleNamespace(partition=[[0], [1]])
        X, labels = np.arange(16, dtype=float)[:, None], np.repeat([0, 1], 8)
        fitted, scored = [], []

        def fit(model, features, y):
            fitted.append(set(features[:, 0]))
            return {"rows": len(y)}

        def predict(model, features):
            scored.append(set(features[:, 0]))
            return np.zeros(len(features), dtype=int)

        with patch.object(CalibratedExperts, "fit", fit), patch.object(CalibratedExperts, "predict", predict):
            _, predictions, receipts = crossfit(network, X, labels)
        self.assertEqual(len(receipts), 5)
        self.assertEqual(set.union(*scored), set(X[:, 0]))
        self.assertTrue(all(not a & b for a, b in zip(fitted[:4], scored)))
        self.assertEqual(fitted[-1], set(X[:, 0]))
        self.assertEqual(predictions.tolist(), [0] * 16)

    def test_strong_nonparametric_control_can_win_selection(self):
        self.assertEqual(choose_candidate({"split": 40, "centroid": 42, "single": 41},
                                         {"split": 900, "centroid": 100, "single": 300}), "centroid")
        self.assertEqual(choose_candidate({"split": 42, "centroid": 42},
                                         {"split": 900, "centroid": 100}), "centroid")

    def test_rejects_cross_partition_and_nonfinite_calibration(self):
        with self.assertRaises(ValueError):
            CalibratedExperts(SimpleNamespace(partition=[[0], [1]]), RoutingCalibration([[1], [0]]))
        with self.assertRaises(ValueError):
            RoutingCalibration([[0], [1]]).fit([[np.nan, 0]], [np.zeros((1, 1))] * 2, [0])

    def test_authored_goldens_agree_with_public_executor(self):
        sys.path.insert(0, str(ROOT.parent / "memory-cell-v13"))
        import tasks
        from routing_experiment import holdout_rows
        rows = holdout_rows(tasks)
        for row in rows[:72]:
            self.assertTrue(tasks.score_prediction(row, row["label"])["correct"], row["skill"])
        old = {" ".join(r["text"].casefold().split()) for split in ("train", "calibration", "test") for r in tasks.load_split(split)}
        new = {" ".join(r["text"].casefold().split()) for r in rows}
        self.assertFalse(old & new, "new held wording duplicates an old request")
        self.assertEqual(len(rows[72:]), 12)


if __name__ == "__main__":
    unittest.main()
