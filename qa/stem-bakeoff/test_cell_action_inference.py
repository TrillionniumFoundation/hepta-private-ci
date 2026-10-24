from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from cell_action_inference import predict_action_rows
from test_cell_action_prepare import BINDINGS, IDENTITY, fixture, prepare


class LabelFreeActionInferenceTests(unittest.TestCase):
    def test_no_query_labels_metrics_or_fitting_and_frozen_controls_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepare(root/"prepared")
            candidates = fixture("holdout", 4)
            with patch("cell_action_evaluate.group_weighted_metrics", side_effect=AssertionError("labels must not be scored")):
                result = predict_action_rows(candidates.features, candidates.rows, feature_identity=IDENTITY,
                    prepared_dir=root/"prepared", output_dir=root/"predictions", input_bindings=BINDINGS, prediction_role="fixture")
            self.assertNotIn("labels", result)
            self.assertFalse(result["plan"]["labels_or_outcomes_received"])
            self.assertFalse(result["plan"]["metrics_computed"])
            self.assertEqual(result["source_ids"], [r["source_id"] for r in candidates.rows])
            self.assertEqual(result["plan"]["groups"], 4)
            run = result["runs"][0]
            for mode in ("linear", "gated", "residual"):
                arm = run["arms"][mode]
                self.assertNotIn("semantic", arm)
                self.assertTrue(arm["fresh_process"]["bitwise_equal_logits_and_probabilities"])
                self.assertEqual(set(arm["controls"]), {"parameters_off", "shuffled_parameters"})
                path = root/"predictions"/run["directory"]/arm["controls"]["parameters_off"]["prediction_file"]
                with np.load(path, allow_pickle=False) as archive:
                    np.testing.assert_array_equal(archive["probabilities"], np.tile(arm["calibration"]["prior"], (len(candidates.rows), 1)))

    def test_gold_fields_unavailable_features_and_unbound_sources_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepare(root/"prepared")
            candidates = fixture("holdout", 4)
            gold = [dict(row, label=1) for row in candidates.rows]
            nan = candidates.features.copy()
            nan[0, 0] = np.nan
            overlap = [dict(row, group_id="train-0") for row in candidates.rows]
            wrong = dict(BINDINGS, proposal_plan_sha256="f"*64)
            cases = [(candidates.features, gold, BINDINGS), (nan, candidates.rows, BINDINGS),
                     (candidates.features, overlap, BINDINGS), (candidates.features, candidates.rows, wrong)]
            for index, (features, rows, bindings) in enumerate(cases):
                output = root/f"bad-{index}"
                with self.assertRaises(ValueError):
                    predict_action_rows(features, rows, feature_identity=IDENTITY, prepared_dir=root/"prepared",
                        output_dir=output, input_bindings=bindings, prediction_role="fixture")
                self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
