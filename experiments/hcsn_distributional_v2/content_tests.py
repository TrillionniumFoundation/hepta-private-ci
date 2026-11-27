"""Tests of study integrity and optimizer-selection boundaries."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import subprocess
import sys

import numpy as np
import torch

from experiments.hcsn_free_boundary_v1 import training
from .content_analysis import audit_predictions, exact_sign_flip, holm
from .content_study import batch, evaluate, file_hash, write_json
from .content_training import train_candidate


class StudyIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def test_sign_flip_extreme_zero_and_permutation(self):
        self.assertEqual(exact_sign_flip(np.ones(8)), 2/256)
        self.assertEqual(exact_sign_flip(np.zeros(8)), 1)
        differences = np.array([.2, -.1, .4, -.2, .1, .2, -.4, .5])
        self.assertEqual(exact_sign_flip(differences), exact_sign_flip(differences[::-1]))
        np.testing.assert_allclose(holm([.01, .03, .05, .2]), [.04, .09, .1, .2], rtol=0, atol=1e-15)

    def test_prediction_coordinates_and_scores_are_independently_checked(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "predictions.npz"
            y = np.array([[-100, 1], [0, -100]])
            logits = np.array([[0., 1.], [2., 0.]], dtype=np.float32)
            ce = (np.logaddexp(0, -1)+np.logaddexp(0, -2))/2
            data = dict(logits=logits, predictions=np.array([1, 0]), labels=np.array([1, 0]),
                        supervised=y!=-100, sample_indices=np.array([0, 1]), step_indices=np.array([1, 0]))
            np.savez_compressed(path, **data)
            checked = audit_predictions(path, y, dict(accuracy=1., cross_entropy=float(ce), supervised_positions=2))
            self.assertEqual(checked["accuracy"], 1)
            data["sample_indices"] = np.array([1, 0])
            np.savez_compressed(path, **data)
            with self.assertRaisesRegex(AssertionError, "sample coordinates"):
                audit_predictions(path, y, dict(accuracy=1., cross_entropy=float(ce), supervised_positions=2))

    def test_cpu_overrun_and_selection_are_recorded_on_synthetic_train_only(self):
        with tempfile.TemporaryDirectory() as folder, torch.random.fork_rng():
            torch.manual_seed(39)
            data = dict(x=torch.randn(6, 4, 5), dt=torch.full((6, 4), .8),
                        y=torch.tensor([[-100, -100, -100, i%3] for i in range(6)]))
            old = training.evaluate
            try:
                training.evaluate = evaluate
                result = train_candidate(data, data, "distribution_free_dual", 101, .003,
                    Path(folder) / "candidate", cpu_seconds=.001, width=10, batch_size=3)
            finally:
                training.evaluate = old
            self.assertGreaterEqual(result["training_cpu_seconds"], .001)
            self.assertGreater(result["overrun_seconds"], 0)
            self.assertEqual(result["primary_cpu_targets"], [.001])
            self.assertEqual(result["best"]["crossed_cpu_targets"], [.001])
            self.assertEqual(result["updates"], 1)
            self.assertTrue(all(r["max_abs"] > 0 for r in result["selected_parameter_changes"].values()))
            points = json.loads((Path(folder) / "candidate/checkpoints.json").read_bytes())
            self.assertEqual(result["checkpoints"], points)

    def test_cooperative_stop_drains_real_child_and_preserves_wait4(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output, protocol_path = root / "study", root / "protocol.json"
            output.mkdir()
            jobs = [dict(task="selective_copy", model="two_gates", seed=i) for i in range(3)]
            protocol = dict(source_files_sha256={}, data={}, jobs=jobs, execution=dict(workers=1))
            write_json(protocol_path, protocol)
            write_json(output / "REGISTRATION.json", dict(protocol_sha256=file_hash(protocol_path)))
            child = ("from pathlib import Path\n"
                     f"Path({str(output / 'STOP_REQUESTED.json')!r}).write_text('{{\"reason\":\"test drain\"}}')\n"
                     "print(sum(i*i for i in range(200000)))\n")
            real_popen = subprocess.Popen
            def launch(_, **kwargs):
                return real_popen([sys.executable, "-c", child], **kwargs)
            with patch("experiments.hcsn_distributional_v2.content_study.subprocess.Popen", side_effect=launch):
                result = batch(protocol_path, output)
            self.assertEqual(result["status"], "aborted")
            self.assertEqual(result["completed"], 1)
            self.assertEqual(result["unstarted"], jobs[1:])
            self.assertEqual(result["records"][0]["returncode"], 0)
            self.assertGreater(result["complete_child_cpu_seconds"], 0)
            self.assertTrue((output / "ABORTED.json").is_file())
            self.assertFalse((output / "COMPLETE.json").exists())


if __name__ == "__main__":
    unittest.main()
