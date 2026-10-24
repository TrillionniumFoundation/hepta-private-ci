import tempfile
import unittest
from pathlib import Path

import numpy as np

from cell_learning_models import NumpyCellHead
from cell_regularized_training import fit_path, matmul_flops


class RegularizedTrainingTests(unittest.TestCase):
    def fixture(self):
        rng = np.random.default_rng(17)
        x = rng.normal(size=(64, 8))
        y = (x[:, 0] > 0).astype(int)
        return x, y

    def test_tuning_stops_path_and_restores_selected_checkpoint(self):
        x, y = self.fixture()
        head, report = fit_path(x, y, x, 1-y, np.ones(len(y)), mode="linear", seed=7, l2=.1)
        self.assertEqual(report["selected_checkpoint_step"], 10)
        self.assertEqual(report["optimizer_steps"], 40)
        self.assertTrue(report["early_stopped"])
        self.assertEqual(head.digest(), report["checkpoint_history"][0]["tensor_sha256"])
        self.assertNotEqual(head.digest(), report["last_update_tensor_sha256"])
        self.assertEqual(report["example_updates"], 40*len(y))
        expected = 40*matmul_flops(8, 2, 4, "linear", 64, True)+3*matmul_flops(8, 2, 4, "linear", 64)
        self.assertEqual(report["executed_dense_matmul_flops"], expected)

    def test_regularization_reduces_weight_norm(self):
        x, y = self.fixture()
        a, _ = fit_path(x, y, x, y, np.ones(len(y)), mode="linear", seed=7, l2=.1)
        b, _ = fit_path(x, y, x, y, np.ones(len(y)), mode="linear", seed=7, l2=1.)
        self.assertLess(np.linalg.norm(b.W), np.linalg.norm(a.W))

    def test_nonlinear_paths_artifact_and_cost_accounting(self):
        x, y = self.fixture()
        with tempfile.TemporaryDirectory() as directory:
            for mode in ("gated", "residual"):
                head, report = fit_path(x, y, x, y, np.ones(len(y)), mode=mode,
                                       seed=7, l2=.1, checkpoints=(2, 5))
                path = Path(directory)/mode
                head.save(path, "identity")
                restored = NumpyCellHead.load(path, "identity")
                np.testing.assert_array_equal(head.predict_logits(x), restored.predict_logits(x))
                self.assertEqual(report["optimizer_state_bytes"], 2*head.tensor_bytes)
                self.assertGreater(report["executed_dense_matmul_flops"], 0)
                self.assertGreater(report["cpu_ns"], 0)

    def test_parameter_ceiling_and_invalid_grid_fail(self):
        x, y = self.fixture()
        with self.assertRaises(ValueError):
            fit_path(x, y, x, y, np.ones(len(y)), mode="linear", seed=7, l2=.1,
                     max_parameters=8)
        with self.assertRaises(ValueError):
            fit_path(x, y, x, y, np.ones(len(y)), mode="linear", seed=7, l2=.1,
                     checkpoints=(10, 2))


if __name__ == "__main__":
    unittest.main()
