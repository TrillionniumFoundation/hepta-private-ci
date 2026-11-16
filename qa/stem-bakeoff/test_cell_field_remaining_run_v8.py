"""Frozen entry, retained stop checkpoints and persistence-failure semantics."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from cell_field_common_run_v8 import file_hash, read, write
from cell_field_remaining_run_v8 import execute_one, frozen_plan, parity, write_trace
from cell_field_state import CellTrainingState
from test_cell_field_policy_v7 import fixture


class RemainingRunnerTests(unittest.TestCase):
    def test_draft_or_changed_mechanism_rejected_before_real_execution(self):
        protocol = Path(__file__).with_name("cell_field_remaining_protocol_v8.json")
        with tempfile.TemporaryDirectory() as temp:
            target, plan = Path(temp)/"protocol.json", read(protocol)
            plan["status"] = "DRAFT"
            write(target, plan)
            with self.assertRaises(ValueError):
                frozen_plan(target, file_hash(target))
            plan["status"] = "FROZEN"
            write(target, plan)
            self.assertEqual(frozen_plan(target, file_hash(target)), plan)
            plan["mechanism"]["commit_stride"] = 8
            write(target, plan)
            with self.assertRaises(ValueError):
                frozen_plan(target, file_hash(target))

    def test_stop_preimage_restores_exactly_without_becoming_complete_parity(self):
        state, train, panels, anchors, _ = fixture()
        after = state.clone()
        action = np.zeros((1, state.parameter_count))
        after.advance(*train, intervention=.02*action[0])
        with tempfile.TemporaryDirectory() as temp:
            methods = {}
            for method in ("full_adjoint_remaining", "terminal_field8_remaining"):
                record = {"status": "not_executed_rejected", "completed_steps": 1, "terminal_state_sha256": after.digest()}
                result = {"state": after, "states": [state, after], "actions": action,
                    "old_losses": np.stack([anchors, anchors]), "plans": [], "record": record}
                directory = Path(temp)/method
                write_trace(directory, result)
                methods[method] = read(directory/"result.json")
                restored = CellTrainingState.load(directory/"checkpoints/1", after.bindings,
                    after.protocol, after.contexts, after.digest())
                self.assertEqual(restored.digest(), after.digest())
                self.assertEqual(methods[method]["checkpoint_cuts"], [0, 1])
            paired = parity(Path(temp), methods)
            self.assertTrue(paired["same_available_prefix_within_1e_10"])
            self.assertFalse(paired["complete"])
            self.assertFalse(paired["passed"])

    def test_model_exception_kept_but_storage_exception_aborts(self):
        state, train, panels, anchors, _ = fixture()
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)/"model_error"
            with patch("cell_field_remaining_v8.execute_remaining", side_effect=RuntimeError("fixture failure")):
                row = execute_one(directory, state, train, panels+panels, anchors, "myopic_h1", "b"*64, "c"*64)
            self.assertEqual(row["status"], "actual_error")
            self.assertFalse(row["retained_prefix_available"])
            self.assertIsNone(row["completed_steps"])
            self.assertEqual(json.loads((directory/"result.json").read_text()), row)
            with patch("cell_field_remaining_v8.execute_remaining", return_value={"record": {}}), \
                    patch("cell_field_remaining_run_v8.write_trace", side_effect=OSError("fixture full disk")):
                with self.assertRaises(OSError):
                    execute_one(Path(temp)/"disk_error", state, train, panels+panels, anchors, "myopic_h1", "b"*64, "c"*64)


if __name__ == "__main__":
    unittest.main()
