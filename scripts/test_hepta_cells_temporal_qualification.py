"""Independent derivative and actual optimizer-continuation qualification."""

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from hepta_cells.temporal import TemporalConfig, TemporalKernel
from hepta_cells.temporal_qualification import (
    check_temporal_gradients,
    run_temporal_reference_probe,
)
from hepta_pred1.models import Model


class TemporalQualificationTests(unittest.TestCase):
    def setUp(self):
        self.kernel = TemporalKernel("gradient-test", TemporalConfig(2, 1, 2, hidden_dim=3))
        self.x = np.random.default_rng(98).normal(0, 0.2, (4, 4, 2))
        self.actions = np.array([[0.0], [1.0], [1.0], [0.0]])
        self.allowed = np.array([[True, False], [False, True], [True, False], [True, True]])

    def test_post_training_derivatives_and_restore_use_actual_shared_kernel(self):
        with tempfile.TemporaryDirectory() as directory:
            result = run_temporal_reference_probe(directory, seeds=(41,), updates=3)
            self.assertTrue(result["passed"], result)
            self.assertEqual(len(result["attempts"]), 2)
            data_digests = {row["training"]["data_sha256"] for row in result["attempts"]}
            self.assertEqual(len(data_digests), 1)
            for row in result["attempts"]:
                self.assertEqual(row["training"]["validated_updates"], 3)
                self.assertNotEqual(
                    row["training"]["parent_weights_sha256"],
                    row["gradient_audit"]["weights_sha256"],
                )
                self.assertEqual(
                    row["gradient_audit"]["coordinates_checked"],
                    row["training"]["resources"]["parameters"],
                )
                self.assertTrue((Path(directory) / row["checkpoint"]).is_file())
            self.assertFalse(result["architecture_ranking_established"])

    def test_audit_detects_corrupt_analytic_gradient_without_mutating_parent(self):
        original = Model.loss_and_grads
        before = (self.kernel.weights_sha256, self.kernel.optimizer_sha256)

        def wrong_gradient(model, *args, **kwargs):
            loss, gradients = original(model, *args, **kwargs)
            gradients["Wn"] = gradients["Wn"] + 0.01
            return loss, gradients

        with patch.object(Model, "loss_and_grads", wrong_gradient):
            report = check_temporal_gradients(self.kernel, self.x, self.actions, self.allowed)
        self.assertFalse(report["passed"])
        failed = [row["parameter"] for row in report["tensors"] if not row["passed"]]
        self.assertEqual(failed, ["Wn"])
        self.assertEqual(before, (self.kernel.weights_sha256, self.kernel.optimizer_sha256))

    def test_bounds_and_unknown_labels_do_not_claim_gradient_evidence(self):
        report = check_temporal_gradients(
            self.kernel, self.x, self.actions, np.ones_like(self.allowed)
        )
        self.assertTrue(report["passed"])
        self.assertEqual(sum(row["analytic_nonzero_scalars"] for row in report["tensors"]), 0)
        oversized = TemporalKernel("large", replace(self.kernel.config, hidden_dim=32))
        with self.assertRaisesRegex(ValueError, "<=2048"):
            check_temporal_gradients(oversized, self.x, self.actions, self.allowed)
        with self.assertRaisesRegex(ValueError, "over-budget"):
            check_temporal_gradients(self.kernel, self.x, self.actions, self.allowed.astype(int))


if __name__ == "__main__":
    unittest.main()
