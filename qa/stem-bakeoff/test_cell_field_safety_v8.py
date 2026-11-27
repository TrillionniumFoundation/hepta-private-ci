"""Joint feasibility, exact nonlinear replay and proposal information boundaries."""

import unittest
from unittest.mock import patch

import numpy as np

from cell_field_joint_search_v8 import joint_project
from cell_field_proposal_v8 import make_proposal
from cell_field_repair_v7 import panel_losses
from cell_field_safety_v8 import repair_sequence
from cell_learning_models import NumpyCellHead, normalize_features
from test_cell_field_policy_v7 import fixture


class JointOldFilterTests(unittest.TestCase):
    def test_joint_constraints_find_witness_outside_original_weighted_ray(self):
        gradients = np.array([[1., 0.], [0., -1.], [1., 4.], [0., 0.]])
        offsets, anchors = np.array([1.6, 1.2, 1., .9]), np.ones(4)
        oracle = lambda action: (offsets+gradients@action, gradients)
        weighted = np.array([.6, -.2])
        for length in np.geomspace(1e-6, 1e6, 500):
            old_ray = np.clip(-length*weighted, -1., 1.)
            self.assertTrue(np.any(oracle(old_ray)[0] > anchors))
        action, losses, record = joint_project(np.zeros(2), anchors, 1., oracle)
        self.assertEqual(record["status"], "certified", record)
        self.assertTrue(np.all(losses <= anchors))
        np.testing.assert_array_equal(losses, oracle(action)[0])
        self.assertLessEqual(len(record["trials"]), 64)

    def test_actual_four_panel_h8_and_full_optimizer_receipts_replay(self):
        for mode in ("linear", "gated"):
            state, train, panels, anchors, _ = fixture(mode)
            before = state.digest()
            gradient = state.head.loss_gradients(normalize_features(train[0]), train[1], 0.)[1]
            gradient = np.concatenate([gradient[name].ravel() for name in state.names])
            intended = np.tile(4./np.sqrt(state.parameter_count)*np.sign(gradient), (8, 1))
            result = repair_sequence(state, train, panels, intended, anchors)
            self.assertTrue(result["record"]["certified"], result["record"])
            actual = state.clone()
            for k, action in enumerate(result["actions"]):
                self.assertEqual(actual.advance(*train, intervention=.02*action), result["receipts"][k])
                self.assertEqual(actual.digest(), result["states"][k+1].digest())
                np.testing.assert_array_equal(panel_losses(actual.head, panels), result["old_losses"][k+1])
                self.assertTrue(np.all(result["old_losses"][k+1] <= anchors))
            self.assertEqual(state.digest(), before)
            for row in result["record"]["step_records"]:
                self.assertLessEqual(row["panel_batches"], 65)

    def test_single_panel_rejection_is_atomic_with_zero_slack_and_all_trials(self):
        state, train, panels, _, _ = fixture()
        panels[-1] = panels[-1][0], (panels[-1][1]+1) % 4
        anchors, before = panel_losses(state.head, panels), state.digest()
        result = repair_sequence(state, train, panels, np.zeros((8, state.parameter_count)),
            anchors, action_bound=1e-12)
        self.assertFalse(result["record"]["certified"])
        self.assertEqual(result["state"].digest(), before)
        self.assertEqual(result["actions"].shape, (0, state.parameter_count))
        self.assertEqual(result["record"]["original_old_anchors"], anchors.tolist())
        first = result["record"]["step_records"][0]
        self.assertEqual(first["global_feasibility"], "unknown")
        self.assertGreater(first["intended_old_losses"][3], anchors[3])
        self.assertTrue(first["search"]["trials"])
        self.assertTrue(all("action" in row for row in first["search"]["trials"]))

    def test_oracle_error_preserves_trials_and_never_becomes_infeasibility(self):
        def broken(action):
            raise RuntimeError("induced actual oracle failure")
        for initial in (None, (np.ones(4)*2, np.ones((4, 2)))):
            action, _, record = joint_project(np.zeros(2), np.ones(4), 1., broken, initial=initial)
            self.assertIsNone(action)
            self.assertEqual(record["status"], "unresolved")
            self.assertEqual(record["global_feasibility"], "unknown")
            self.assertEqual(record["trials"][-1]["error"]["type"], "RuntimeError")

    def test_common_proposal_full_field_parity_and_h1_exact_loss2(self):
        state, train, panels, anchors, _ = fixture("gated")
        before = state.digest()
        for horizon in (1, 8):
            outputs = {method: make_proposal(state, train, panels, panels, anchors,
                method=method, horizon=horizon, old_weight=.25, current_dispersion=.5)
                for method in ("full", "future_field", "loss2")}
            np.testing.assert_allclose(outputs["full"]["actions"], outputs["future_field"]["actions"],
                rtol=1e-11, atol=1e-12)
            if horizon == 1:
                np.testing.assert_array_equal(outputs["full"]["actions"], outputs["loss2"]["actions"])
            for value in outputs.values():
                self.assertLessEqual(value["record"]["projected_stationarity_linf"], 1e-12)
                self.assertEqual(value["record"]["actual_risk_backtracking_rollouts"], 0)
                self.assertFalse(value["record"]["predicted_old_constraints"])
        self.assertEqual(state.digest(), before)

    def test_partial_failed_panel_batch_charges_every_attempted_head(self):
        state, train, panels, anchors, _ = fixture()
        original, calls = NumpyCellHead.loss_gradients, []

        def counted(head, *args, **kwargs):
            calls.append(1)
            if len(calls) == 7:
                raise RuntimeError("second head in first prospective old batch failed")
            return original(head, *args, **kwargs)

        with patch.object(NumpyCellHead, "loss_gradients", new=counted):
            result = repair_sequence(state, train, panels, np.zeros((1, state.parameter_count)),
                anchors, horizon=1)
        row = result["record"]["step_records"][0]
        self.assertEqual(row["status"], "unresolved")
        self.assertEqual(row["attempted_panel_head_evaluations"], 2)
        self.assertEqual(row["panel_batches"], 0)
        self.assertEqual(result["record"]["panel_head_evaluations"], 6)
        self.assertEqual(row["oracle_failures"][0]["panel_index"], 1)
        self.assertEqual(result["state"].digest(), state.digest())


if __name__ == "__main__":
    unittest.main()
