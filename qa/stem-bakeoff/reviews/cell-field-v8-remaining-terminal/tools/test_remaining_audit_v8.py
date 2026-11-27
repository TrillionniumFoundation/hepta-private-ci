"""Independent forward algebra, nonlinear receipts, and fail-closed evidence."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

CODE = Path(__file__).resolve().parents[1]/"hepta-repo-v8/qa/stem-bakeoff"
sys.path.insert(0, str(CODE))

from cell_field_common_run_v8 import read, write
from cell_field_remaining_run_v8 import execute_one
from cell_field_terminal_v8 import METHODS, make_terminal_proposal
from remaining_audit_case_v8 import inspect_case
from remaining_audit_core_v8 import canonical, check_seal, file_hash, independent_response
from test_cell_field_policy_v7 import fixture
from test_cell_field_response_v7 import controlled_example


class IndependentRemainingAuditTests(unittest.TestCase):
    def test_independent_forward_and_lstsq_maps_match_all_four_declared_models(self):
        for mode in ("linear", "gated"):
            state, train, panels, _ = controlled_example(mode)
            for method in METHODS:
                for horizon in (1, 8, 32):
                    expected = make_terminal_proposal(state, train, panels[:4], panels[4:], method=method, remaining=horizon)
                    actual = independent_response(state, train, panels, method, horizon)
                    np.testing.assert_array_equal(actual["terminal"], expected["reference_terminal_state"])
                    np.testing.assert_array_equal(actual["panels"], expected["reference_terminal_panels"])
                    np.testing.assert_allclose(actual["map"], expected["first_action_map"], rtol=2e-8, atol=1e-11)
                    if actual["field"] is not None:
                        np.testing.assert_allclose(actual["field"], expected["initial_field_observation"], rtol=2e-8, atol=1e-9)

    def test_actual32_trace_then_changed_moment_or_forecast_is_detected(self):
        state, train, panels, anchors, _ = fixture("gated")
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)/"control"
            execute_one(directory, state, train, panels+panels, anchors, "terminal_field8_remaining", "b"*64, "c"*64)
            result = inspect_case(directory, state, train, panels+panels, "terminal_field8_remaining", "b"*64, "c"*64)
            self.assertEqual((result["completed"], result["known_replayed_steps"], result["proposal_checks"]), (True, 32, 32))
            path = directory/"plans.npz"
            with np.load(path, allow_pickle=False) as a:
                arrays = {k: a[k] for k in a.files}
            arrays["first_action_maps"][0, 0, 0] += 1e-4
            np.savez_compressed(path, **arrays)
            with self.assertRaisesRegex(ValueError, "independent first-action response"):
                inspect_case(directory, state, train, panels+panels, "terminal_field8_remaining", "b"*64, "c"*64)
            trace_path = directory/"trajectory.npz"
            with np.load(trace_path, allow_pickle=False) as a:
                trace = {k: a[k] for k in a.files}
            trace["states"][1, state.parameter_count] += 1e-7
            np.savez_compressed(trace_path, **trace)
            with self.assertRaisesRegex(ValueError, "full states"):
                inspect_case(directory, state, train, panels+panels, "terminal_field8_remaining", "b"*64, "c"*64)

    def test_recorded_zero_step_error_keeps_complete_origin_and_unqualified_status(self):
        state, train, panels, anchors, _ = fixture()
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)/"stopped"
            with patch("cell_field_remaining_v8.make_terminal_proposal", side_effect=RuntimeError("fixture proposal error")):
                execute_one(directory, state, train, panels+panels, anchors, "myopic_h1", "b"*64, "c"*64)
            result = inspect_case(directory, state, train, panels+panels, "myopic_h1", "b"*64, "c"*64)
            self.assertFalse(result["completed"])
            self.assertTrue(result["available"])
            self.assertTrue(result["actual_errors"])
            self.assertEqual(result["terminal_state_sha256"], state.digest())
            self.assertEqual(result["known_replayed_steps"], 0)

    def test_seal_rejects_extra_or_mutated_member_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            payload = root/"result.json"
            write(payload, {"x": 1})
            write(root/"control_seal.json", {"files": {"result.json": {
                "sha256": file_hash(payload), "bytes": payload.stat().st_size}}})
            seal = file_hash(root/"control_seal.json")
            check_seal(root, seal)
            payload.write_bytes(canonical({"x": 2})+b"\n")
            with self.assertRaisesRegex(ValueError, "sealed bytes"):
                check_seal(root, seal)
            write(root/"extra.json", {})
            with self.assertRaisesRegex(ValueError, "inventory"):
                check_seal(root, seal)


if __name__ == "__main__":
    unittest.main()
