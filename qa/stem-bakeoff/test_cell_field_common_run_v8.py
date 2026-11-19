"""Runner qualification on synthetic existing-engine states; no real-fit run."""

import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from cell_field_common_objective_v8 import BRANCHES, rollout32
from cell_field_common_run_v8 import execute_fit, file_hash, frozen_plan, read, write
from cell_field_state import CellTrainingState
from test_cell_field_response_v7 import controlled_example


class CommonRunnerTests(unittest.TestCase):
    def test_draft_and_parameter_changes_reject_before_execution(self):
        original = read(Path(__file__).with_name("cell_field_common_objective_protocol_v8.json"))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "protocol.json"
            plan = copy.deepcopy(original)
            plan["status"] = "DRAFT"
            write(path, plan)
            with self.assertRaisesRegex(ValueError, "must be remotely frozen"):
                frozen_plan(path, file_hash(path))
            plan["status"] = "FROZEN"
            write(path, plan)
            self.assertEqual(frozen_plan(path, file_hash(path)), plan)
            plan["mechanism"]["effort_price"] = .04
            write(path, plan)
            with self.assertRaises(ValueError):
                frozen_plan(path, file_hash(path))

    def test_failed_branch_retains_proposal_and_never_substitutes_zero(self):
        state, train, panels, _ = controlled_example("linear")
        before, calls = state.digest(), []
        def injected(*args, **kwargs):
            calls.append(np.asarray(args[3]).copy())
            if len(calls) == 2:
                raise RuntimeError("injected actual trajectory failure")
            return rollout32(*args, **kwargs)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "synthetic-fit"
            with patch("cell_field_common_objective_v8.rollout32", side_effect=injected):
                results = execute_fit(directory, state, train, panels)
            self.assertEqual(len(calls), 6)
            self.assertEqual([r["branch"] for r in results], list(BRANCHES))
            self.assertEqual(results[1]["status"], "actual_error")
            self.assertEqual(sum(r["status"] == "completed_unguarded_diagnostic" for r in results), 5)
            saved = np.load(directory / BRANCHES[1] / "proposed_actions.npy", allow_pickle=False)
            np.testing.assert_array_equal(saved, calls[1])
            self.assertGreater(np.linalg.norm(saved), 0.)
            self.assertFalse((directory / BRANCHES[1] / "terminal").exists())
            self.assertEqual(state.digest(), before)

    def test_saved_six_branch_census_and_full_checkpoint_replay(self):
        state, train, panels, _ = controlled_example("gated")
        initial = state.digest()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "synthetic-fit"
            results = execute_fit(directory, state, train, panels)
            self.assertEqual([r["branch"] for r in results], list(BRANCHES))
            self.assertTrue(all(r["status"] == "completed_unguarded_diagnostic" for r in results))
            self.assertEqual(state.digest(), initial)
            for result in results:
                target = directory / result["branch"]
                with np.load(target / "trajectory.npz", allow_pickle=False) as arrays:
                    actual = state.clone()
                    self.assertEqual(arrays["losses"].shape, (33, 8))
                    for k, action in enumerate(arrays["actions"]):
                        self.assertEqual(actual.advance(*train, intervention=.02 * action), result["receipts"][k])
                        np.testing.assert_array_equal(actual.vector(), arrays["states"][k+1])
                        self.assertEqual(actual.digest(), result["state_sha256"][k+1])
                restored = CellTrainingState.load(target / "terminal", state.bindings, state.protocol,
                                                  state.contexts, result["terminal_state_sha256"])
                self.assertEqual(restored._metadata(), actual._metadata())
                np.testing.assert_array_equal(restored.vector(), actual.vector())
                self.assertEqual(read(target / "result.json"), result)
                for forecast in result["forecasts_on_actual_actions"].values():
                    self.assertAlmostEqual(result["actual_common_objective"] - forecast["tangent_common_objective"],
                                           forecast["objective_error_actual_minus_tangent"], places=14)
            with np.load(directory / "reference.npz", allow_pickle=False) as arrays:
                self.assertEqual(arrays["field_initial"].shape, (264, 156))
                self.assertEqual(arrays["field_input_offsets"][-1], len(arrays["field_inputs"]))
                np.testing.assert_allclose(arrays["full_maps"], arrays["field_maps"], rtol=1e-12, atol=1e-12)


if __name__ == "__main__":
    unittest.main()
