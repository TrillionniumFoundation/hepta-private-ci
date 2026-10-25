"""Counterfactual execution and failure-retention tests, using synthetic data."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from cell_field_action_control import build_action_model
from cell_field_action_run import _anchors, _candidate, branch
from cell_field_control import build_reference
from cell_field_state import CellTrainingState, dataset_digest
from cell_learning_models import NumpyCellHead


class ActionRunTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(891)
        self.x = rng.normal(size=(12, 2))
        self.y = np.tile(np.arange(4), 3)
        self.state = CellTrainingState(NumpyCellHead(2, 4, "linear", seed=7),
            bindings={"fixture": "synthetic-no-study-data"},
            contexts={"train": dataset_digest(self.x, self.y)}, active_context="train")
        for _ in range(3):
            self.state.advance(self.x, self.y)
        self.reference = build_reference(self.state, self.x, self.y,
            ((self.x, self.y), (self.x, self.y)), horizon=2)

    def test_same_actions_apply_after_adam_and_do_not_mutate_checkpoint(self):
        actions = np.zeros((2, self.state.parameter_count))
        actions[0, 0] = 0.07
        before = self.state.digest()
        result = branch(self.state, self.reference, actions, self.x, np.array([0, 1, 2, 3]))
        expected = self.state.clone()
        for action in actions:
            expected.advance(self.x, self.y, intervention=0.02 * action,
                             mask=np.ones(self.state.parameter_count, dtype=bool))
        self.assertEqual(self.state.digest(), before)
        np.testing.assert_array_equal(result["states"][-1], expected.vector())
        np.testing.assert_array_equal(result["terminal_probabilities"], expected.head.predict_proba(self.x))
        np.testing.assert_array_equal(result["retention_probabilities"][0],
                                      self.state.head.predict_proba(self.x)[[0, 1, 2, 3]])
        self.assertEqual(result["midpoint_state"].step_count, self.state.step_count + 1)

    def test_different_start_and_second_intervention_reject(self):
        actions = np.zeros((2, self.state.parameter_count))
        actions[1, 0] = 0.01
        with self.assertRaises(ValueError):
            branch(self.state, self.reference, actions, self.x, np.array([0]))
        actions[1, 0] = 0
        changed = self.state.clone()
        changed.advance(self.x, self.y)
        with self.assertRaises(ValueError):
            branch(changed, self.reference, actions, self.x, np.array([0]))

    def test_solver_failure_keeps_raw_candidate_without_executing(self):
        plan = {"h": 0.02, "effort_price": 0.1, "action_bound": 1.0,
                "current_shift": 0.03, "direct_coefficient": 0.03,
                "feasibility_tolerance": 1e-9, "solver": {"gap_tolerance": 1e-9,
                "max_iterations": 300, "ftol": 1e-13}}
        initial = {"initial_id": "fixture", "seed": 7, "head": "linear", "anchor_offset": 0,
                   "initial_index": 0, "warmup_index": 0, "old_probe_anchor": 1.0,
                   "reference_path": "references/fixture.npz", "model_paths": {"loss2": "models/fixture.npz"}}
        method = {"method_id": "loss2_h1_direct_soft", "observation": "loss2", "lookahead": 1,
                  "objective": "direct_soft"}
        proposal = {"status": "solver_failed_or_unresolved", "u": np.array([np.nan]),
                    "problem": {}, "record": {"status": "solver_failed_or_unresolved", "gap": np.inf}}
        with tempfile.TemporaryDirectory() as directory:
            with patch("cell_field_action_run.plan_action", return_value=proposal):
                record, executable = _candidate(Path(directory), initial, method, self.state,
                    self.reference, {"loss2": build_action_model(self.reference, observation="loss2")}, plan)
            self.assertEqual(record["status"], "solver_failure")
            self.assertIsNone(executable)
            with np.load(Path(directory) / record["paths"]["candidate"], allow_pickle=False) as saved:
                self.assertTrue(np.isnan(saved["u"]).all())
            metadata = json.loads((Path(directory) / record["paths"]["candidate_record"]).read_text())
            self.assertEqual(metadata["record"]["gap"], {"__nonfinite__": "+inf"})
            plan["evaluation_horizon"] = 2
            u = np.zeros(self.state.parameter_count)
            wrong_actions = np.zeros((2, self.state.parameter_count))
            wrong_actions[0, 0] = 0.01
            inconsistent = {"status": "qualified", "u": u, "actions": wrong_actions,
                            "problem": {}, "record": {"status": "qualified"}}
            with patch("cell_field_action_run.plan_action", return_value=inconsistent):
                rejected, executable = _candidate(Path(directory) / "mismatch", initial, method,
                    self.state, self.reference,
                    {"loss2": build_action_model(self.reference, observation="loss2")}, plan)
            self.assertEqual(rejected["status"], "solver_failure")
            self.assertIsNone(executable)
            self.assertEqual(rejected["error"]["type"], "ValueError")

    def test_post_prediction_warmup_failure_clears_all_scores(self):
        plan = {"registered_warmups": 1, "registered_anchors": 1, "seeds": [7],
                "head_modes": ["linear"], "classes": 4, "projection": {"width": 2},
                "optimizer": {}, "warmup_steps": 1, "anchor_offsets": [0],
                "evaluation_horizon": 2, "h": 0.02, "task": "synthetic fixture"}
        inputs = {"plan": plan, "protocol_sha256": "fixture",
                  "receipt": {"files": {key: {"sha256": "0" * 64}
                    for key in ("sources.json", "train_labels.json")}}}
        split = {key: (self.x, self.y) for key in
                 ("old_train", "current_train", "old_probe", "current_probe")}
        with tempfile.TemporaryDirectory() as directory:
            with patch("cell_field_action_run.save_arrays", side_effect=OSError("injected archive failure")):
                warmups, initials, runtime, warm_probs, initial_probs = _anchors(
                    Path(directory), inputs, self.x, split, {}, {})
            self.assertEqual(warmups[0]["status"], "initial_failure")
            self.assertEqual(initials[0]["status"], "initial_failure")
            self.assertTrue(np.isnan(warm_probs).all())
            self.assertTrue(np.isnan(initial_probs).all())
            self.assertIsNone(runtime[0][0])


if __name__ == "__main__":
    unittest.main()
