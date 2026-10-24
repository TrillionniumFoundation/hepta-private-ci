import unittest

import numpy as np

from calibrated_cell_runtime import CalibratedCellRuntime
from cell_batch_runtime import BatchRuntimeError
from cell_calibration_v2 import apply_calibrator_logits, fit_calibrator
from cell_learning_metrics import probabilities
from cell_learning_models import NumpyCellHead

IDENTITY = "a" * 64


class CalibratedRuntimeTests(unittest.TestCase):
    def fixture(self):
        rng = np.random.default_rng(35)
        train = rng.normal(size=(32, 6))
        cal = rng.normal(size=(20, 6))
        head = NumpyCellHead(6, 2, "gated", rank=2, seed=7)
        head.train(train, (train[:, 0] > 0).astype(int), steps=20)
        head.feature_identity = IDENTITY
        fit = fit_calibrator(head.predict_logits(cal), (cal[:, 0] > 0).astype(int))
        self.assertTrue(fit["converged"])
        return head, fit, rng.normal(size=(3, 6))

    def predict(self, runtime, x):
        return runtime.predict(x, source_digests=[f"{i:064x}" for i in range(len(x))],
                               feature_identity=IDENTITY, generation=1)

    def test_calibrated_fanout_matches_scalar_and_respects_distinct_calibration(self):
        head, fit, x = self.fixture()
        different = dict(fit, alpha=0., bias=-2.)
        runtime = CalibratedCellRuntime([head, head, head], [fit, fit, different],
                                       ["a", "b", "c"], ["task"] * 3, IDENTITY)
        result = self.predict(runtime, x)
        expected = probabilities(apply_calibrator_logits(head.predict_logits(x), fit))
        np.testing.assert_allclose(result["probabilities"][:, 0], expected, atol=1e-12, rtol=1e-12)
        np.testing.assert_array_equal(result["probabilities"][:, 0], result["probabilities"][:, 1])
        np.testing.assert_allclose(result["probabilities"][:, 2, 1], 1/(1 + np.exp(2)))
        self.assertEqual(result["head_evaluations"], 6)
        self.assertEqual(runtime.accounting()["declared_task_count"], 1)
        self.assertEqual(runtime.accounting()["unique_head_and_calibration_states"], 2)
        self.assertEqual(runtime.accounting()["owned_calibration_tensor_bytes"], 64)

    def test_private_learning_or_caller_mutation_cannot_change_published_snapshot(self):
        head, fit, x = self.fixture()
        runtime = CalibratedCellRuntime([head], [fit], ["a"], ["task"], IDENTITY)
        before = self.predict(runtime, x)["probabilities"]
        fit["bias"] = 9
        head.train(np.eye(6), np.arange(6) % 2, steps=3)
        np.testing.assert_array_equal(before, self.predict(runtime, x)["probabilities"])
        with self.assertRaises(ValueError):
            runtime.calibration.setflags(write=True)

    def test_invalid_calibration_and_stale_features_reject(self):
        head, fit, x = self.fixture()
        with self.assertRaisesRegex(BatchRuntimeError, "converged"):
            CalibratedCellRuntime([head], [dict(fit, converged=False)], ["a"], ["task"], IDENTITY)
        runtime = CalibratedCellRuntime([head], [fit], ["a"], ["task"], IDENTITY)
        with self.assertRaisesRegex(BatchRuntimeError, "stale"):
            runtime.predict(x, source_digests=["0" * 64] * 3, feature_identity="b" * 64, generation=1)
        self.assertEqual(runtime.router.runtime.dispatch_calls, 0)


if __name__ == "__main__":
    unittest.main()
