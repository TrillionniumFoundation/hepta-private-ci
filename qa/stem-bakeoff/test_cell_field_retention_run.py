"""Fresh-process nonlinear feedback and retained-failure integration checks."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from cell_field_control import build_reference
from cell_field_features import file_hash
from cell_field_retention_control import fit_retention_controller
from cell_field_retention_run import _condition
from cell_field_state import CellTrainingState, dataset_digest
from cell_learning_models import NumpyCellHead


class RetentionRunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rng = np.random.default_rng(420)
        old_x, current_x = rng.normal(size=(20, 3)), rng.normal(size=(20, 3))
        old_y, current_y = (old_x[:, 0] > 0).astype(int), (current_x[:, 1] > 0).astype(int)
        cls.state = CellTrainingState(NumpyCellHead(3, 2, "gated", seed=7),
            bindings={"fixture": "synthetic-only"},
            contexts={"old": dataset_digest(old_x, old_y),
                      "current": dataset_digest(current_x, current_y)}, active_context="old")
        for _ in range(8):
            cls.state.advance(old_x, old_y)
        cls.state.select_context("current")
        cls.ref = build_reference(cls.state, current_x, current_y,
            ((current_x, current_y), (old_x, old_y)), horizon=4)
        cls.target = np.column_stack([np.full(5, -0.03),
            cls.ref.observations[0, 1] - cls.ref.observations[:, 1]])
        cls.features = current_x

    def policies(self):
        return [fit_retention_controller(self.ref, mask="all", mode=mode,
                                         target=self.target) for mode in ("loss2", "full")]

    def test_condition_and_cold_process_continuation_preserve_actual_feedback(self):
        control, oracle = self.policies()
        before = self.state.digest()
        hashes = {name: file_hash(Path(__file__).with_name(name)) for name in
                  ("cell_field_retention_control.py", "cell_field_state.py")}
        with tempfile.TemporaryDirectory() as directory:
            record, probabilities = _condition(Path(directory), "synthetic", 0,
                self.state, self.ref, control, oracle, self.features, {"fixture": True}, hashes)
            self.assertEqual(record["status"], "completed", record.get("error"))
            self.assertEqual(probabilities.shape, (20, 2))
            self.assertTrue(record["recovery"]["all_exact"])
            self.assertEqual([row["start_step"] for row in record["recovery"]["checks"]], [0, 2])
            self.assertTrue(all(row["matches"]["transition_receipts"]
                                for row in record["recovery"]["checks"]))
            with np.load(Path(directory) / record["paths"]["trajectory"], allow_pickle=False) as arrays:
                self.assertEqual(arrays["planned_actions"].shape[0:2], (4, 4))
            self.assertEqual(len(json.loads((Path(directory) / record["paths"]["solver"]).read_bytes())), 4)
        self.assertEqual(self.state.digest(), before)

    def test_nonfinite_solver_failure_is_recorded_without_losing_condition(self):
        control, oracle = self.policies()
        control.records.append({"failure": "nonfinite", "optimality_gap_bound": float("inf")})
        with tempfile.TemporaryDirectory() as directory:
            with patch("cell_field_retention_run.run_retention_nonlinear", side_effect=RuntimeError("budget")):
                record, probabilities = _condition(Path(directory), "synthetic", 0,
                    self.state, self.ref, control, oracle, self.features, {"fixture": True}, {})
            self.assertEqual(record["status"], "failed")
            self.assertTrue(np.isnan(probabilities).all())
            failure = json.loads((Path(directory) / "failures/synthetic-all-loss2.json").read_bytes())
            self.assertEqual(failure["solver_records"][0]["optimality_gap_bound"], {"nonfinite": "inf"})


if __name__ == "__main__":
    unittest.main()
