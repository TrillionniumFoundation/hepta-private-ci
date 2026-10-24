import unittest
from unittest.mock import patch

import numpy as np

from cell_calibration_bounded import fit_bounded_calibrator
from bounded_cell_runtime import BoundedCalibratedCellRuntime
from cell_learning_models import NumpyCellHead
from cell_serving_compare import compare_condition


class ServingComparisonTests(unittest.TestCase):
    def fixture(self, mode):
        identity, context = "a"*64, "b"*64
        meta = {"feature_identity": identity, "calibration_context_sha256": context,
                "task_id": "fixture_only", "generation": 1}
        x = np.random.default_rng(17).normal(size=(4, 770)).astype(np.float32)
        rows = [{"source_id": f"cal-{i}", "group_id": f"group-{i}"} for i in range(4)]
        heads, fits = [], []
        for seed in range(4):
            head = NumpyCellHead(770, 2, mode, rank=4, seed=seed)
            head.feature_identity = identity
            # An explicit synthetic receipt fixture, never research evidence.
            head.report = {"trained_tensor_sha256": head.digest(), "optimizer_steps": 1,
                           "test_fixture_not_learning_evidence": True}
            fitted = fit_bounded_calibrator(np.array([-2., 1., -1., 2.]), np.array([0, 1, 0, 1]), rows,
                effective_training_prior=[.5, .5], bindings={"feature_identity": identity,
                    "predictor_sha256": head.digest(), "calibration_context_sha256": context})
            heads.append(head)
            fits.append(fitted)
        return heads, fits, meta, x, [f"{i:064x}" for i in range(4)]

    def test_three_modes_physical_scalar_cache_and_selective_agree(self):
        for mode in ("linear", "gated", "residual"):
            with self.subTest(mode=mode):
                heads, fits, meta, x, sources = self.fixture(mode)
                report = compare_condition(heads, fits, meta, x, sources, 11, repetitions=2)
                self.assertTrue(report["bitwise_physical_logical"])
                self.assertTrue(report["scalar_decisions_equal"])
                self.assertTrue(report["cached_equal"])
                self.assertEqual(report["logical_states"], 4)
                self.assertEqual(report["declared_tasks"], 1)
                self.assertEqual(report["top3_head_evaluations"], 12)
                self.assertEqual(report["top3_served_predictions"], 36)
                self.assertEqual(report["physical_accounting"]["private_parameter_tensor_bytes"], 11*heads[0].tensor_bytes)
                self.assertEqual(report["logical_accounting"]["owned_parameter_tensor_bytes"], 4*heads[0].tensor_bytes)

    def test_mismatched_physical_output_is_not_reported_as_parity(self):
        import cell_serving_compare as module
        original = module.physical_prediction
        def changed(*args, **kwargs):
            result = original(*args, **kwargs)
            result["probabilities"][0, 0, 1] += .01
            return result
        heads, fits, meta, x, sources = self.fixture("linear")
        with patch.object(module, "physical_prediction", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "bitwise"):
                compare_condition(heads, fits, meta, x, sources, 11, repetitions=1)

    def test_wrong_three_states_cannot_pass_as_the_fixed_routing_plan(self):
        original = BoundedCalibratedCellRuntime.predict
        def changed(runtime, *args, **kwargs):
            if kwargs.get("top_k") == 3:
                kwargs["router_scores"] = -kwargs["router_scores"]
            return original(runtime, *args, **kwargs)
        heads, fits, meta, x, sources = self.fixture("linear")
        with patch.object(BoundedCalibratedCellRuntime, "predict", new=changed):
            with self.assertRaisesRegex(ValueError, "selective"):
                compare_condition(heads, fits, meta, x, sources, 11, repetitions=1)


if __name__ == "__main__":
    unittest.main()
