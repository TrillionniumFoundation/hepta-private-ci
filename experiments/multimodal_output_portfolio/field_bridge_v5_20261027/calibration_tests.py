"""Behavioral tests for saved-fold replay and the empirical action gate; no torch."""

import copy
import subprocess
import sys
import unittest

import numpy as np

from .calibration import DEFAULT_EVIDENCE, calibrate_all, calibrate_saved, choose, decision, load_saved, predict4


class GateTests(unittest.TestCase):
    def test_strict_threshold_equality_and_ties_keep_baseline(self):
        equality = choose([1.0, 1.5, 1.25, 0.0], 0, 0.5)
        self.assertEqual(equality["chosen"], 0)
        self.assertFalse(equality["override"])
        self.assertEqual(choose([1.0, 1.0, 1.0, 1.0], 3, 0.0)["chosen"], 3)
        self.assertEqual(choose([3.0, 3.0, 1.0, 0.0], 3, 0.5)["chosen"], 3)
        above = choose([1.0, np.nextafter(1.5, 2.0), 1.25, 0.0], 0, 0.5)
        self.assertEqual(above["chosen"], 1)
        self.assertTrue(above["override"])
        self.assertFalse(above["certificate"])

    def test_common_prediction_offset_preserves_decision(self):
        predictions = np.asarray([1.0, 3.0, 2.0, 0.0])
        first = choose(predictions, 3, 2.5)
        shifted = choose(predictions + 100, 3, 2.5)
        self.assertEqual(first["chosen"], shifted["chosen"])
        self.assertEqual(first["margin"], shifted["margin"])

    def test_invalid_inputs_rejected(self):
        for values, baseline, tau in (([1, 2, 3], 0, 0), ([1, 2, 3, float("nan")], 0, 0),
                                      ([1, 2, 3, 4], 4, 0), ([1, 2, 3, 4], True, 0),
                                      ([1, 2, 3, 4], 0, -1), ([1, 2, 3, 4], 0, float("inf"))):
            with self.subTest(values=values, baseline=baseline, tau=tau), self.assertRaises(ValueError):
                choose(values, baseline, tau)


class SavedEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = calibrate_all()
        cls.bank, cls.controllers, _ = load_saved(DEFAULT_EVIDENCE, 17)

    def test_real_saved_folds_replay_and_shared_tau_is_pooled_residual_max(self):
        for seed, report in self.report["seeds"].items():
            with self.subTest(seed=seed):
                residuals = []
                for mode in ("field", "richer"):
                    evidence = report["modes"][mode]
                    self.assertLessEqual(evidence["prediction_replay_max_abs_error"], 1e-14)
                    self.assertEqual(len(evidence["rows"]), 24)
                    for row in evidence["rows"]:
                        residuals.extend(abs(value) for value in row["advantage_residual4"])
                        self.assertEqual(row["tau"], report["tau"])
                        baseline = report["baseline_action"]
                        self.assertEqual(row["advantage_residual4"][baseline], 0.0)
                        if row["override"]:
                            self.assertGreater(row["margin"], report["tau"])
                            # Descriptive property on calibration rows, not future coverage.
                            self.assertGreater(row["target4"][row["chosen"]], row["target4"][baseline])
                self.assertEqual(report["tau"], max(residuals))

    def test_baseline_differs_from_seed17_label_continuation(self):
        report = self.report["seeds"]["17"]
        self.assertEqual(report["baseline_action"], 2)
        self.assertEqual(report["label_reference_action"], 1)
        self.assertFalse(report["label_continuation_matches_baseline"])
        self.assertFalse(report["coverage_claim"])

    def test_batch_single_and_receipt_prediction_agree(self):
        head = self.controllers["controllers"]["field"]
        raw = [row["state"] for row in self.bank["records"][:2]]
        batched = predict4(head, raw)
        np.testing.assert_allclose(predict4(head, raw[0]), batched[0], rtol=0, atol=1e-14)
        receipt = decision(head, raw[0], 2, self.report["seeds"]["17"]["tau"])
        np.testing.assert_allclose(receipt["predictions"], batched[0], rtol=0, atol=1e-14)
        self.assertEqual(receipt["ref"], receipt["baseline_action"])
        with self.assertRaises(ValueError):
            predict4(head, raw[0][:-1])

    def test_saved_prediction_tamper_and_trajectory_leakage_rejected(self):
        for leak in (False, True):
            controllers = copy.deepcopy(self.controllers)
            choices = controllers["all_candidates"]["field"]
            fold = choices["candidates"][choices["selected_index"]]["folds"][0]
            if leak:
                fold["training_trajectories"].append(fold["held_out_trajectory"])
            else:
                fold["predictions"][0][0] += 1e-4
            with self.subTest(leak=leak), self.assertRaises(ValueError):
                calibrate_saved(self.bank, controllers)

    def test_import_and_calibration_need_no_torch(self):
        package = __package__ + ".calibration"
        code = ("import importlib,sys; m=importlib.import_module(" + repr(package) + "); "
                "m.calibrate_all(); assert 'torch' not in sys.modules")
        subprocess.run([sys.executable, "-c", code], check=True)


if __name__ == "__main__":
    unittest.main()
