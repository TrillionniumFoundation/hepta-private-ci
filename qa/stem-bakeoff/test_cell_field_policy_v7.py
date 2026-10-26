"""Real four-panel Adam safety, full/field parity and pending-action recovery."""

import copy
import hashlib
import unittest

import numpy as np

from cell_field_controller_v7 import load_snapshot
from cell_field_policy_v7 import execute_policy, resume_policy
from cell_field_repair_v7 import panel_losses, repair_sequence
from cell_field_state import CellTrainingState, dataset_digest
from cell_learning_models import NumpyCellHead, canonical


def fixture(mode="linear"):
    rng = np.random.default_rng(4407)
    x = rng.normal(size=(48, 8))
    y = np.arange(48) % 4
    train = x, y
    panels = [(x+scale*rng.normal(size=x.shape), y)
        for scale in (0., .02, -.02, .04)]
    state = CellTrainingState(NumpyCellHead(8, 4, mode, seed=7), seed=17,
        bindings={"fixture": "v7-controller", "protocol_sha256": "a"*64},
        contexts={"current_train": dataset_digest(*train)}, active_context="current_train")
    for _ in range(32):
        state.advance(*train)
    config = {"steps": 32, "dt": .02, "effort_price": .03, "action_bound": 4.,
        "old_weight": .25, "current_dispersion": .5, "relinearizations": 2}
    return state, train, panels, panel_losses(state.head, panels), config


class PanelPolicyTests(unittest.TestCase):
    def test_actual_four_panel_sequence_and_complete_receipts_replay(self):
        for mode in ("linear", "gated"):
            state, train, panels, anchors, _ = fixture(mode)
            origin = state.digest()
            result = repair_sequence(state, train, panels, np.zeros((8, state.parameter_count)), anchors)
            self.assertTrue(result["record"]["certified"], result["record"])
            actual = state.clone()
            for k, action in enumerate(result["actions"]):
                self.assertEqual(actual.advance(*train, intervention=.02*action), result["receipts"][k])
                self.assertEqual(actual.digest(), result["states"][k+1].digest())
                np.testing.assert_array_equal(panel_losses(actual.head, panels), result["old_losses"][k+1])
                self.assertTrue(np.all(result["old_losses"][k+1] <= anchors))
            self.assertEqual(state.digest(), origin)
            self.assertEqual(result["record"]["committed_optimizer_steps"], 0)

    def test_single_failing_panel_rejects_whole_block_and_keeps_original_threshold(self):
        state, train, panels, _, _ = fixture()
        panels[-1] = panels[-1][0], (panels[-1][1]+1) % 4
        anchors = panel_losses(state.head, panels)
        origin = state.digest()
        result = repair_sequence(state, train, panels, np.zeros((8, state.parameter_count)),
            anchors, action_bound=1e-12)
        self.assertFalse(result["record"]["certified"])
        self.assertEqual(result["state"].digest(), origin)
        self.assertEqual(result["actions"].shape, (0, state.parameter_count))
        self.assertEqual(result["record"]["original_old_anchors"], anchors.tolist())
        first = result["record"]["step_records"][0]["trials"][0]["old_losses"]
        self.assertTrue(np.all(np.asarray(first)[:3] <= anchors[:3]))
        self.assertGreater(first[3], anchors[3])
        self.assertTrue(all(len(r["trials"]) <= 16 for r in result["record"]["step_records"]))

    def test_field_full_parity_and_mid_plan_resume_retains_seven_original_actions(self):
        state, train, panels, anchors, config = fixture()
        field = execute_policy(state, train, panels, panels, anchors, "future_field_h8", config)
        full = execute_policy(state, train, panels, panels, anchors, "full_h8", config)
        for result in (field, full):
            self.assertEqual(result["record"]["status"], "completed", result["record"])
            self.assertEqual(result["record"]["completed_steps"], 32)
        np.testing.assert_allclose(field["actions"], full["actions"], rtol=1e-11, atol=1e-12)
        np.testing.assert_allclose(field["state"].vector(), full["state"].vector(), rtol=1e-11, atol=1e-12)
        snapshot, mid = field["controllers"][17], field["states"][17]
        self.assertEqual((snapshot["plan_origin_step"], snapshot["action_cursor"], snapshot["plan_horizon"]), (16, 1, 8))
        raw = canonical(snapshot)
        restored = resume_policy(mid, raw, snapshot["contract"], train, panels, panels,
            expected_controller_sha256=hashlib.sha256(raw).hexdigest())
        self.assertEqual(restored["record"]["status"], "completed", restored["record"])
        self.assertEqual(restored["record"]["steps"][0]["resume_verified_steps"], 7)
        np.testing.assert_array_equal(restored["actions"], field["actions"][17:])
        self.assertEqual(restored["receipts"], field["receipts"][17:])
        self.assertEqual(restored["state"].digest(), field["state"].digest())
        self.assertEqual(restored["controllers"][-1]["receipt_chain"], field["controllers"][-1]["receipt_chain"])
        self.assertEqual(restored["controllers"][-1]["contract"], snapshot["contract"])

    def test_checkpoint_rejects_reanchoring_cursor_state_and_pending_action_substitution(self):
        state, train, panels, anchors, config = fixture()
        config["relinearizations"] = 0
        result = execute_policy(state, train, panels, panels, anchors, "future_field_h8", config)
        self.assertEqual(result["record"]["status"], "completed", result["record"])
        snapshot, mid = result["controllers"][17], result["states"][17]
        load_snapshot(canonical(snapshot), mid, snapshot["contract"])
        mutations = []
        wrong = copy.deepcopy(snapshot); wrong["action_cursor"] += 1; mutations.append(wrong)
        wrong = copy.deepcopy(snapshot); wrong["contract"]["original_old_anchors"][0] += .1; mutations.append(wrong)
        wrong = copy.deepcopy(snapshot); wrong["resolved_actions"][1][0] += .001; mutations.append(wrong)
        for wrong in mutations:
            with self.assertRaises(ValueError):
                load_snapshot(canonical(wrong), mid, snapshot["contract"])
        other = mid.clone(); other.step_count += 1
        with self.assertRaises(ValueError):
            load_snapshot(canonical(snapshot), other, snapshot["contract"])
        with self.assertRaisesRegex(ValueError, "input identities"):
            resume_policy(mid, canonical(snapshot), snapshot["contract"],
                (train[0]+.001, train[1]), panels, panels)


if __name__ == "__main__":
    unittest.main()
