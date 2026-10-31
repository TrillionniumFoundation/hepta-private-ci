"""Tests target stale kernels, loss masking, saved execution, and DP independence."""

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

import numpy as np
import torch

from ..round7.model import JointCell
from ..round7.posthoc.independent_joint_optimal import build_public_graph, prepare_kernel
from ..round7.task import TaskParameters, features
from .calibration import (FixedCellCalibrator, calibration_loss, frozen_cell_digest,
                          load_calibrated, save_calibrated)
from .calibration_audit import zero_event_price_audit


class CalibrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.graph = build_public_graph([replace(TaskParameters(), horizon=3, ordinary_count=1)])
        cls.inputs = torch.tensor(np.stack([features(s) for s in cls.graph.states]), dtype=torch.float64)

    def test_readout_content_changes_do_not_change_cell(self):
        torch.manual_seed(23)
        model = FixedCellCalibrator(JointCell("first_passage", n_grid=5))
        before = prepare_kernel(model, self.graph)
        model.set_stage("content_readout")
        fingerprint = frozen_cell_digest(model)
        with torch.no_grad():
            model.content[0].weight.add_(0.5)
            model.readout[0].weight.add_(0.1)
        after = prepare_kernel(model, self.graph)
        np.testing.assert_array_equal(before.transition, after.transition)
        self.assertEqual(fingerprint, frozen_cell_digest(model))
        trainable = {name for name, p in model.named_parameters() if p.requires_grad}
        self.assertTrue(trainable and all(name.startswith(("content.", "readout.")) for name in trainable))

    def test_zero_event_price_matches_public_dp_for_every_law(self):
        for mode in ("direct", "continuous", "clocked", "first_passage"):
            with self.subTest(mode=mode):
                model = FixedCellCalibrator(JointCell(mode, n_grid=5))
                audit = zero_event_price_audit(self.graph, prepare_kernel(model, self.graph))
                self.assertTrue(audit["passed"])

    def test_loss_excludes_illegal_actions_and_uses_per_state_weights(self):
        prediction = torch.tensor([[[3.0, 100.0], [2.0, 4.0]]], requires_grad=True)
        target = torch.zeros_like(prediction)
        legal = torch.tensor([[[True, False], [True, True]]])
        weights = torch.tensor([[0.25, 0.75]])
        loss, _ = calibration_loss(prediction, target, legal, weights)
        self.assertAlmostEqual(float(loss.detach()), 9.75)
        loss.backward()
        self.assertEqual(float(prediction.grad[0, 0, 1]), 0.0)

    def test_checkpoint_roundtrip_preserves_two_encoder_execution(self):
        model = FixedCellCalibrator(JointCell("clocked", n_grid=5))
        with torch.no_grad():
            model.content[0].weight.add_(0.2)
        metadata = {"frozen_cell_sha256": frozen_cell_digest(model)}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.json"
            save_calibrated(model, path, metadata)
            restored, actual = load_calibrated(path)
            self.assertEqual(actual, metadata)
            mass = model.initial(len(self.inputs))
            for left, right in zip(model.advance(mass, self.inputs), restored.advance(mass, self.inputs)):
                torch.testing.assert_close(left, right, rtol=0, atol=0)
            torch.testing.assert_close(model.values(mass, self.inputs), restored.values(mass, self.inputs), rtol=0, atol=0)


if __name__ == "__main__":
    unittest.main()
