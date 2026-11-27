"""Physical hold and same-state diagnostic integrity; synthetic planning data."""

import unittest
from unittest.mock import patch

import numpy as np

from cell_field_repair_v7 import repair_sequence
from loss2_stop_diagnostic import METHODS, diagnose_origin, parameter_hold
from test_cell_field_policy_v7 import fixture


class StopDiagnosticTests(unittest.TestCase):
    def test_hold_preserves_parameters_but_advances_complete_optimizer_and_rejects_tiny_box(self):
        for mode in ("linear", "gated"):
            state, train, panels, anchors, configuration = fixture(mode)
            for _ in range(4):
                state.advance(*train)
            before = state.digest()
            configuration["action_bound"] = 40.
            held = parameter_hold(state, train, panels, anchors, configuration)
            self.assertTrue(held["record"]["certified"], held["record"])
            self.assertEqual(held["record"]["optimizer_updates"], 16)
            self.assertEqual(held["state"].step_count, state.step_count+8)
            np.testing.assert_allclose(held["state"].parameter_vector(), state.parameter_vector(), rtol=0, atol=1e-15)
            self.assertGreater(np.linalg.norm(held["state"].vector()[state.parameter_count:]-state.vector()[state.parameter_count:]), 0.)
            replay = state.clone()
            for k, action in enumerate(held["actions"]):
                self.assertEqual(replay.advance(*train, intervention=.02*action), held["record"]["receipts"][k])
                self.assertEqual(replay.digest(), held["states"][k+1].digest())
            configuration["action_bound"] = 1e-15
            denied = parameter_hold(state, train, panels, anchors, configuration)
            self.assertEqual(denied["record"]["status"], "hold_outside_original_box")
            self.assertFalse(denied["record"]["certified"])
            self.assertEqual(denied["state"].digest(), before)
            self.assertEqual(denied["actions"].shape, (0, state.parameter_count))
            self.assertEqual(state.digest(), before)

    def test_exact_executed_full_actions_use_each_predictors_returned_nominal(self):
        state, train, panels, anchors, configuration = fixture()
        before = state.digest()
        result = diagnose_origin(state, train, panels, panels, anchors, configuration)
        self.assertTrue(result["record"]["full_actual_safe_witness"], result["record"]["branches"]["full"])
        arrays = result["arrays"]
        rows = [row for row in result["record"]["terminal_prediction_errors"] if row["target"] == "full"]
        self.assertEqual({row["predictor"] for row in rows}, set(METHODS))
        for row in rows:
            method = row["predictor"]
            expected = arrays[method+"_reference_observations"][-1]+np.einsum("kqp,kp->q",
                arrays[method+"_maps"], arrays["full_actions"]-arrays[method+"_nominal_reference_actions"])
            np.testing.assert_array_equal(row["predicted_terminal_panels"], expected)
            self.assertEqual(row["status"], "computed")
        np.testing.assert_allclose(arrays["full_actions"], arrays["future_field_actions"], rtol=1e-10, atol=1e-12)
        self.assertEqual(state.digest(), before)

    def test_no_solver_result_is_replaced_by_the_separate_hold_witness(self):
        state, train, panels, anchors, configuration = fixture()
        for _ in range(4):
            state.advance(*train)
        configuration["action_bound"] = 40.
        unavailable = {"record": {"status": "tangent_infeasible"}, "actions": None}
        with patch("loss2_stop_diagnostic.make_plan", return_value=unavailable), \
                patch("loss2_stop_diagnostic.repair_sequence") as repair:
            result = diagnose_origin(state, train, panels, panels, anchors, configuration)
        repair.assert_not_called()
        self.assertTrue(result["record"]["hold_actual_safe_witness"])
        self.assertFalse(result["record"]["full_actual_safe_witness"])
        for method in METHODS:
            self.assertEqual(result["record"]["branches"][method]["status"], "plan_tangent_infeasible")

    def test_corrupt_complete_repair_state_is_preserved_as_diagnostic_error(self):
        state, train, panels, anchors, configuration = fixture()
        configuration["relinearizations"] = 0
        before = state.digest()
        def corrupt(*args, **kwargs):
            result = repair_sequence(*args, **kwargs)
            if result["record"]["certified"]:
                result["states"][-1].rng.random()
            return result
        with patch("loss2_stop_diagnostic.repair_sequence", side_effect=corrupt):
            result = diagnose_origin(state, train, panels, panels, anchors, configuration)
        for method in METHODS:
            self.assertEqual(result["record"]["branches"][method]["status"], "unresolved")
            self.assertFalse(result["record"]["branches"][method]["certified"])
        self.assertEqual(state.digest(), before)


if __name__ == "__main__":
    unittest.main()
