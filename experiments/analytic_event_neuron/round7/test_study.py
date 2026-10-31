"""Run failures must leave usable receipts and must never pass an efficacy gate."""

import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import torch

from .model import JointCell
from .study import run_confirmation, checkpoint_path


class StudyFailureTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)

    def test_missing_checkpoint_keeps_incomplete_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = run_confirmation(root, root / "result", allow_development=True, count=1)
            self.assertEqual(result["status"], "incomplete")
            self.assertEqual(result["trajectories"], 0)
            self.assertEqual(result["failures"][0]["status"], "run_aborted")
            self.assertTrue((root / "result" / "RUN_RECEIPT.json").is_file())

    def test_rejected_temperature_fit_is_never_selected_or_substituted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            name = "first_passage_temperature_none_11.json"
            (root / "fits_primary").mkdir()
            (root / "fits_temperature_corrected").mkdir()
            (root / "fits_primary" / name).write_text("rejected")
            with self.assertRaises(ValueError):
                checkpoint_path(root, "first_passage_temperature", "none", 11)
            expected = root / "fits_temperature_corrected" / name
            expected.write_text("registered")
            self.assertEqual(checkpoint_path(root, "first_passage_temperature", "none", 11), expected)

    def test_nonfinite_trajectory_serialization_is_a_retained_failure(self):
        model = JointCell("clocked", n_grid=5)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch("experiments.analytic_event_neuron.round7.study.checkpoint_path", return_value=root / "mock"), \
                 patch("experiments.analytic_event_neuron.round7.study.load_model", return_value=(model, {})), \
                 patch("experiments.analytic_event_neuron.round7.study.run_episode", return_value={"quality": float("nan")}):
                result = run_confirmation(root, root / "result", allow_development=True, count=1)
            self.assertEqual(result["status"], "incomplete")
            self.assertEqual(len(result["failures"]), 6)
            with gzip.open(root / "result" / "trajectories.jsonl.gz", "rt") as source:
                records = [json.loads(line) for line in source]
            self.assertEqual([r["status"] for r in records], ["failed"] * 6)


if __name__ == "__main__":
    unittest.main()
