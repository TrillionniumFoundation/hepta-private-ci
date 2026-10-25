"""Actual Adam integration and replay on synthetic fixtures, not task evidence."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import numpy as np

from cell_field_experiments_v4 import fixed_anchor
from cell_field_mpc_v4 import execute_policy
from cell_field_state import CellTrainingState, dataset_digest
from cell_learning_models import NumpyCellHead, normalize_features


class JointIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = json.loads(Path(__file__).with_name("cell_field_joint_protocol_v4.json").read_bytes())
        rng = np.random.default_rng(8127)
        labels = np.tile(np.arange(4), 4)
        cls.split = {role: (rng.normal(size=(16, 8)), labels.copy()) for role in
                     ("old_train", "old_probe", "current_train", "current_probe")}
        cls.projected = np.concatenate([x for x, _ in cls.split.values()])
        contexts = {role: dataset_digest(*cls.split[role]) for role in ("old_train", "current_train")}
        cls.state = CellTrainingState(NumpyCellHead(8, 4, "linear", seed=7),
            bindings={"test": "joint-v4-fixture"}, contexts=contexts, active_context="old_train")
        for _ in range(12):
            cls.state.advance(*cls.split["old_train"])
        cls.state.select_context("current_train")
        x, y = cls.split["old_probe"]
        cls.anchor = cls.state.head.loss_gradients(normalize_features(x), y, 0.0)[0]

    def test_complete_real_fixed_library_and_shared_checkpoint(self):
        before = self.state.digest()
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "anchor"
            result = fixed_anchor(self.state, self.split, self.plan, self.projected,
                                  np.arange(16), self.anchor, path)
            self.assertEqual((result["registered"], result["completed"]), (49, 49))
            with np.load(path / "actual_trajectories.npz", allow_pickle=False) as arrays:
                self.assertEqual(arrays["states"].shape, (49, 9, 108))
                np.testing.assert_array_equal(arrays["real_delta"][0], np.zeros((9, 2)))
            plans = json.loads((path / "frozen_plan.json").read_bytes())
            self.assertEqual(plans["models"], self.plan["models"])
        self.assertEqual(before, self.state.digest())

    def test_causal_mpc_complete_state_restore_and_exact_replay(self):
        before = self.state.digest()
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "policy"
            result = execute_policy(self.state, self.split, self.plan, self.projected,
                                    self.anchor, "structured4_h8", path)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["completed_steps"], 8)
            self.assertGreater(result["cpu_ns"], 0)
            resumed = CellTrainingState.load(path / "midpoint", self.state.bindings,
                expected_protocol=self.state.protocol, expected_contexts=self.state.contexts)
            for k in range(4, 8):
                with np.load(path / f"plans/{k}.npz", allow_pickle=False) as arrays:
                    resumed.advance(*self.split["current_train"], intervention=self.plan["h"] * arrays["u"])
            self.assertEqual(resumed.digest(), result["terminal_state_sha256"])
            with np.load(path / "trajectory.npz", allow_pickle=False) as arrays:
                np.testing.assert_array_equal(resumed.head.predict_proba(self.projected),
                                              arrays["terminal_probabilities"])
        self.assertEqual(before, self.state.digest())

    def test_failed_post_update_prediction_preserves_actual_progress_and_cost(self):
        real_predict, calls = NumpyCellHead.predict_proba, []

        def fail_after_initial(head, values):
            calls.append(1)
            if len(calls) > 1:
                raise ValueError("injected prediction failure after actual Adam update")
            return real_predict(head, values)

        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "failure"
            with mock.patch.object(NumpyCellHead, "predict_proba", fail_after_initial):
                result = execute_policy(self.state, self.split, self.plan, self.projected,
                                        self.anchor, "zero", path)
            self.assertEqual(result["status"], "execution_failed")
            self.assertEqual(result["completed_steps"], 1)
            self.assertGreater(result["cpu_ns"], 0)
            self.assertEqual(result["steps"][-1]["status"], "execution_failed")
            with np.load(path / "trajectory.npz", allow_pickle=False) as arrays:
                self.assertEqual(len(arrays["states"]), 2)
                self.assertEqual(len(arrays["probabilities"]), 1)
                self.assertTrue(np.isnan(arrays["terminal_probabilities"]).all())


if __name__ == "__main__":
    unittest.main()
