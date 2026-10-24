import copy
from pathlib import Path
import tempfile
import unittest

import numpy as np

from cell_action_cohort import ActionCohort
from cell_action_evaluate import _probabilities, evaluate_action_curve
from cell_action_prepare import sha_file, verify_action_prepared
from test_cell_action_prepare import IDENTITY, fixture, prepare


class ActionEvaluationTests(unittest.TestCase):
    def test_frozen_weight_recovery_controls_and_group_weighted_scores(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepared = prepare(root/"prepared")
            before = sha_file(root/"prepared"/"seal.json")
            holdout = fixture("holdout", 5)
            report = evaluate_action_curve(holdout, feature_identity=IDENTITY, prepared_dir=root/"prepared",
                output_dir=root/"evaluation", holdout_use="fixture")
            self.assertEqual(before, sha_file(root/"prepared"/"seal.json"))
            self.assertEqual(verify_action_prepared(root/"prepared"), prepared)
            self.assertEqual(report["plan"]["labelled_holdout"]["groups"], 5)
            self.assertEqual(report["plan"]["labelled_holdout"]["group_weighted_class_mass"], [3, 2])
            self.assertFalse(report["quality_qualified"])
            run = report["runs"][0]
            self.assertEqual(len(run["arms"]), 8)
            self.assertEqual(run["arms"]["exact"]["semantic"]["coverage"], 0)
            self.assertEqual(run["arms"]["exact"]["semantic"]["overall_success"], 0)
            self.assertIsNone(run["arms"]["exact"]["semantic"]["selective_risk"])
            for mode in ("linear", "gated", "residual"):
                arm = run["arms"][mode]
                self.assertTrue(arm["fresh_process"]["bitwise_equal_logits_and_probabilities"])
                self.assertFalse(arm["fresh_process"]["test_labels_provided_to_child"])
                self.assertEqual(set(arm["controls"]), {"parameters_off", "shuffled_parameters"})
                path = root/"evaluation"/run["directory"]/arm["controls"]["parameters_off"]["prediction_file"]
                with np.load(path, allow_pickle=False) as archive:
                    np.testing.assert_array_equal(archive["logits"], np.zeros((len(holdout.labels), 2)))
                    np.testing.assert_array_equal(archive["probabilities"], np.tile(arm["calibration"]["prior"], (len(holdout.labels), 1)))
                self.assertFalse(arm["controls"]["shuffled_parameters"]["calibration_refitted"])
                self.assertEqual(arm["semantic"]["weighted_class_support"], [3, 2])
            with self.assertRaises(FileExistsError):
                evaluate_action_curve(holdout, feature_identity=IDENTITY, prepared_dir=root/"prepared",
                    output_dir=root/"evaluation", holdout_use="fixture")

    def test_wrong_identity_overlap_or_evaluation_designation_fail_before_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepare(root/"prepared")
            holdout = fixture("holdout", 4)
            rows = list(holdout.rows)
            rows[0] = dict(rows[0], group_id="train-0")
            overlap = ActionCohort(holdout.features, holdout.labels, tuple(rows), "holdout")
            cases = [(holdout, "f"*64, "fixture"), (overlap, IDENTITY, "fixture"),
                     (holdout, IDENTITY, "unregistered")]
            for index, (cohort, identity, designation) in enumerate(cases):
                output = root/f"bad-{index}"
                with self.assertRaises(ValueError):
                    evaluate_action_curve(cohort, feature_identity=identity, prepared_dir=root/"prepared",
                        output_dir=output, holdout_use=designation)
                self.assertFalse(output.exists())

    def test_calibrator_cannot_be_moved_to_another_predictor(self):
        with tempfile.TemporaryDirectory() as directory:
            frozen = prepare(Path(directory)/"prepared")
            spec = copy.deepcopy(frozen["runs"][0]["arms"]["linear"])
            spec["predictor_sha256"] = "f"*64
            with self.assertRaises(ValueError):
                _probabilities(np.zeros((4, 2)), spec, frozen["plan"])


if __name__ == "__main__":
    unittest.main()
