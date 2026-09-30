"""Adversarial support calibration and actual saved-tensor consumer regression."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import torch

from decision_cell_calibration import (joint_support_calibration,
                                       select_confidence_threshold, select_ood_threshold)


def panel():
    labels = {name: np.zeros(8, dtype=np.int64)
              for name in ("action", "target", "disposition", "postcondition", "ood")}
    labels["ood"][-2:] = 1
    probabilities = {name: np.eye(classes, dtype=np.float64)[labels[name]]
                     for name, classes in (("action", 6), ("target", 4), ("disposition", 6),
                                           ("postcondition", 6), ("ood", 2))}
    return probabilities, labels


class JointCalibrationTests(unittest.TestCase):
    def test_saturated_incorrect_confidence_has_no_feasible_threshold(self):
        threshold, metrics = select_confidence_threshold(np.ones(8), np.zeros(8, dtype=bool))
        self.assertIsNone(threshold)
        self.assertEqual(metrics, {"calibration_confidence_coverage": 0.0,
                                   "calibration_confidence_error": None})

    def test_wrong_nonaction_heads_cannot_be_hidden_by_perfect_action(self):
        for head in ("target", "disposition", "postcondition"):
            with self.subTest(head=head):
                probabilities, labels = panel()
                labels[head][:6] = 1
                result = joint_support_calibration(probabilities, labels)
                self.assertEqual(result["calibration_confidence_error"], 0.0)
                self.assertFalse(result["calibration_support_feasible"])
                self.assertEqual(result["calibration_support_mode"], "reject_all")
                self.assertEqual(result["maximum_ood_probability"], 0.0)
                self.assertIsNone(result["calibration_supported_joint_error"])
                self.assertEqual(result["calibration_supported_rows"], 0)

    def test_complete_correct_decisions_keep_nonempty_support(self):
        probabilities, labels = panel()
        result = joint_support_calibration(probabilities, labels)
        self.assertTrue(result["calibration_support_feasible"])
        self.assertEqual(result["calibration_supported_rows"], 6)
        self.assertEqual(result["calibration_supported_joint_error"], 0.0)
        self.assertEqual(result["calibration_ood_false_acceptance"], 0.0)

    def test_inapplicable_target_does_not_reject_correct_decision(self):
        probabilities, labels = panel()
        labels["target"][:] = -1
        result = joint_support_calibration(probabilities, labels)
        self.assertEqual(result["calibration_supported_rows"], 6)

    def test_low_confidence_wrong_postcondition_selects_higher_threshold(self):
        probabilities, labels = panel()
        probabilities["action"][5] = [0.6, 0.4, 0, 0, 0, 0]
        labels["postcondition"][5] = 1
        result = joint_support_calibration(probabilities, labels)
        self.assertEqual(result["minimum_confidence"], 1.0)
        self.assertEqual(result["calibration_supported_rows"], 5)
        self.assertEqual(result["calibration_supported_joint_error"], 0.0)

    def test_correct_ood_rejected_rows_do_not_dilute_supported_errors(self):
        confidence = np.ones(100)
        correct = np.ones(100, dtype=bool)
        correct[0] = False
        eligible = np.zeros(100, dtype=bool)
        eligible[0] = True
        threshold, _ = select_confidence_threshold(confidence, correct, eligible=eligible)
        self.assertIsNone(threshold)

    def test_empty_eligible_population_is_undefined_not_zero_risk(self):
        threshold, metrics = select_confidence_threshold(
            np.ones(4), np.ones(4, dtype=bool), eligible=np.zeros(4, dtype=bool))
        self.assertIsNone(threshold)
        self.assertIsNone(metrics["calibration_confidence_error"])

    def test_ood_rows_count_as_joint_errors_even_with_matching_other_heads(self):
        probabilities, labels = panel()
        # Replicate independent-looking fixture rows only to exercise arithmetic,
        # never as an independence or model-quality claim.
        probabilities = {name: np.repeat(value, 20, axis=0) for name, value in probabilities.items()}
        labels = {name: np.repeat(value, 20) for name, value in labels.items()}
        probabilities["ood"][120] = [1, 0]
        result = joint_support_calibration(probabilities, labels)
        self.assertEqual(result["calibration_supported_joint_errors"], 1)
        self.assertEqual(result["calibration_supported_rows"], 121)
        self.assertAlmostEqual(result["calibration_supported_joint_error"], 1 / 121)

    def test_ood_boundary_is_strict_and_zero_rejects_saturated_zero(self):
        threshold, metrics = select_ood_threshold(np.zeros(4), np.asarray([0, 0, 1, 1]))
        self.assertEqual(threshold, 0.0)
        self.assertEqual(metrics["calibration_ood_false_acceptance"], 0.0)
        self.assertFalse((np.zeros(4) < threshold).any())

    def test_invalid_scores_and_truth_reject(self):
        for confidence in (np.asarray([]), np.asarray([np.nan]), np.asarray([np.inf]),
                           np.asarray([-0.1]), np.asarray([1.1]), np.asarray([True]),
                           np.ones((2, 2)), np.ones(4097)):
            with self.subTest(confidence=str(confidence.shape)):
                with self.assertRaises(ValueError):
                    select_confidence_threshold(confidence, np.ones(confidence.shape, dtype=bool))
        for correct in (np.ones(3, dtype=int), np.ones(2, dtype=bool)):
            with self.assertRaises(ValueError):
                select_confidence_threshold(np.ones(3), correct)
        with self.assertRaises(ValueError):
            select_confidence_threshold(np.ones(3), np.ones(3, dtype=bool), eligible=np.ones(3))

    def test_missing_ood_or_in_domain_population_rejects(self):
        for value in (0, 1):
            probabilities, labels = panel()
            labels["ood"][:] = value
            with self.assertRaises(ValueError):
                joint_support_calibration(probabilities, labels)

    def test_bad_head_shape_normalization_and_labels_reject(self):
        for mutation in ("missing", "shape", "normalization", "nan", "label", "boolean-label"):
            probabilities, labels = panel()
            if mutation == "missing":
                del probabilities["postcondition"]
            elif mutation == "shape":
                probabilities["target"] = np.ones((8, 3)) / 3
            elif mutation == "normalization":
                probabilities["action"][0] *= 0.5
            elif mutation == "nan":
                probabilities["action"][0, 0] = np.nan
            elif mutation == "label":
                labels["target"][0] = -2
            else:
                labels["ood"] = labels["ood"].astype(bool)
            with self.subTest(mutation=mutation):
                with self.assertRaises(ValueError):
                    joint_support_calibration(probabilities, labels)

    def test_calibration_does_not_mutate_supplied_arrays(self):
        probabilities, labels = panel()
        before = copy.deepcopy((probabilities, labels))
        joint_support_calibration(probabilities, labels)
        for group, old in zip((probabilities, labels), before):
            for name in group:
                np.testing.assert_array_equal(group[name], old[name])

    def test_saved_reject_all_thresholds_are_honored_by_real_tensor_consumer(self):
        import decision_cell_bakeoff as bakeoff
        probabilities, labels = panel()
        labels["postcondition"][:6] = 1
        calibration = joint_support_calibration(probabilities, labels)
        calibration["temperatures"] = {name: 1.0 for name in probabilities}
        model = bakeoff.TypedHeads(8, width=4)
        with torch.no_grad():
            for parameter in model.parameters():
                parameter.zero_()
            model.action.bias[0] = 1000
            model.ood.bias[0] = 1000
        metadata = {"base_model": {"snapshot_digest": "a" * 64}, "calibration": calibration}
        with tempfile.TemporaryDirectory() as raw:
            _, artifact = bakeoff.save_head_artifact(Path(raw), "fixture-only", model, metadata)
            manifest = json.loads(Path(artifact["manifest_path"]).read_text())
            bundle = bakeoff._tensor_module.HeadTensorBundleV2(
                manifest_path=Path(artifact["manifest_path"]), manifest_sha256=artifact["manifest_sha256"],
                weights_path=Path(artifact["weights_path"]), weights_sha256=artifact["weights_sha256"],
                expected_base_snapshot="a" * 64, expected_runtime_profile=manifest["runtime_profile"])
            observed = bundle.probabilities(torch.zeros(2, 8), torch.zeros(2, 4, 8))
        self.assertEqual(observed["action"][:, 0].tolist(), [1.0, 1.0])
        self.assertEqual(observed["ood"][:, 1].tolist(), [0.0, 0.0])
        self.assertEqual(observed["supported"].tolist(), [False, False])


if __name__ == "__main__":
    unittest.main()
