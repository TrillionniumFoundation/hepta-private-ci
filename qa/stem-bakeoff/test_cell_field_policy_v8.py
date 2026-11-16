"""V8 stride/forecast distinction, real recovery and explicit version rejection."""

import copy
import hashlib
import unittest

import numpy as np

from cell_field_controller_v7 import load_snapshot as load_old_snapshot
from cell_field_controller_v8 import load_snapshot
from cell_field_policy_v8 import execute_policy, resume_policy
from cell_learning_models import canonical
from test_cell_field_policy_v7 import fixture


class RecedingPrefixTests(unittest.TestCase):
    def test_all_strides_complete_and_resume_exactly_from_real_step17(self):
        for mode, stride in (("linear", 1), ("linear", 2), ("gated", 4), ("gated", 8)):
            state, train, panels, anchors, config = fixture(mode)
            config.update(commit_stride=stride, relinearizations=0)
            result = execute_policy(state, train, panels, panels, anchors, "future_field_h8", config)
            self.assertEqual(result["record"]["status"], "completed", result["record"])
            self.assertEqual(result["record"]["completed_steps"], 32)
            self.assertEqual(len(result["controllers"]), 33)
            for snapshot, physical in zip(result["controllers"], result["states"], strict=True):
                load_snapshot(canonical(snapshot), physical, snapshot["contract"])
            snapshot, mid = result["controllers"][17], result["states"][17]
            self.assertEqual(snapshot["plan_horizon"], stride)
            self.assertEqual(snapshot["forecast_horizon"], 8)
            raw = canonical(snapshot)
            resumed = resume_policy(mid, raw, snapshot["contract"], train, panels, panels,
                expected_controller_sha256=hashlib.sha256(raw).hexdigest())
            self.assertEqual(resumed["record"]["status"], "completed", resumed["record"])
            np.testing.assert_array_equal(resumed["actions"], result["actions"][17:])
            self.assertEqual(resumed["receipts"], result["receipts"][17:])
            self.assertEqual(resumed["state"].digest(), result["state"].digest())
            self.assertEqual(resumed["controllers"][-1]["receipt_chain"], result["controllers"][-1]["receipt_chain"])
            self.assertEqual(result["controllers"][-1]["action_cursor"], stride)

    def test_full_field_equal_protocol_and_prefix_forecast_binding(self):
        state, train, panels, anchors, config = fixture("gated")
        config.update(commit_stride=2, relinearizations=0)
        field = execute_policy(state, train, panels, panels, anchors, "future_field_h8", config)
        full = execute_policy(state, train, panels, panels, anchors, "full_h8", config)
        for result in (field, full):
            self.assertEqual(result["record"]["status"], "completed", result["record"])
        np.testing.assert_allclose(field["actions"], full["actions"], rtol=1e-10, atol=1e-11)
        np.testing.assert_allclose(field["state"].vector(), full["state"].vector(), rtol=1e-10, atol=1e-11)
        snapshot, physical = field["controllers"][17], field["states"][17]
        for key in ("forecast_horizon", "plan_horizon", "action_cursor"):
            bad = copy.deepcopy(snapshot)
            bad[key] += 1
            with self.assertRaises((ValueError, TypeError)):
                load_snapshot(canonical(bad), physical, snapshot["contract"])
        bad = copy.deepcopy(snapshot)
        bad["forecast_actions"][-1][0] += 1e-4
        with self.assertRaises(ValueError):
            load_snapshot(canonical(bad), physical, snapshot["contract"])
        with self.assertRaises(ValueError):
            load_old_snapshot(canonical(snapshot), physical, snapshot["contract"])
        bad = copy.deepcopy(snapshot)
        bad["schema"] = "hepta.cell-field-controller.v7"
        with self.assertRaises(ValueError):
            load_snapshot(canonical(bad), physical, snapshot["contract"])


if __name__ == "__main__":
    unittest.main()
