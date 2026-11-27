"""Integrate seven frozen forecasts, actual branches and full policy serialization."""

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from cell_field_experiments_v5 import fixed_anchor
from cell_field_policy_v5 import execute_policy
from cell_field_run_v5 import save_policy
from cell_field_state import CellTrainingState, dataset_digest
from test_cell_field_response_v5 import example


class RunTests(unittest.TestCase):
    def test_all_fixed_predictions_precede_49_actual_h8_branches(self):
        plan = json.loads((Path(__file__).parent/"cell_field_protocol_v5.json").read_bytes())
        for mode in ("linear", "gated"):
            state, train, probes = example(mode)
            split = {"current_train":train,"current_probe":probes[0],"old_probe":probes[1]}
            before = state.digest()
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory)/"anchor"
                result = fixed_anchor(state,split,plan,probes[0][0],np.arange(20),2.,output)
                self.assertEqual(result["completed"],49)
                self.assertEqual(state.digest(),before)
                frozen = json.loads((output/"frozen_plan.json").read_bytes())
                self.assertEqual(frozen["models"],plan["models"])
                self.assertLessEqual((output/"frozen_plan.json").stat().st_mtime_ns,
                                     (output/"actual_trajectories.npz").stat().st_mtime_ns)
                with np.load(output/"frozen_predictions.npz",allow_pickle=False) as p:
                    self.assertEqual(p["predictions"].shape,(7,49,9,2))
                    np.testing.assert_allclose(p["predictions"][4],p["predictions"][5],rtol=2e-5,atol=1e-8)
                    np.testing.assert_allclose(p["predictions"][5],p["predictions"][6],rtol=2e-4,atol=1e-8)
                with np.load(output/"actual_trajectories.npz",allow_pickle=False) as actual:
                    self.assertEqual(actual["states"].shape,(49,9,3*state.parameter_count))
                    self.assertTrue(np.isfinite(actual["observations"]).all())

    def test_serialized_midpoint_has_exact_full_state_identity(self):
        original,train,probes = example("gated")
        state = CellTrainingState(original.head,bindings={"test":"pipeline"},
            protocol=original.protocol,contexts={"current_train":dataset_digest(*train)})
        state.set_vector(original.vector())
        state.step_count = original.step_count
        split = {"current_train":train,"current_probe":probes[0],"old_probe":probes[1]}
        config = {"steps":32,"dt":.02,"effort_price":.1,"action_bound":1.,"old_weight":0.,
                  "hard_retention":True,"backtracking":[1.,.5,0.]}
        result = execute_policy(state,split,3.,"response_h8_guarded",config)
        self.assertEqual(result["record"]["completed_steps"],32)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/"policy"
            record = save_policy(result,probes[0][0],output)
            restored = CellTrainingState.load(output/"midpoint",state.bindings,state.protocol,
                                              state.contexts,record["state_digests"][16])
            self.assertEqual(restored.digest(),result["states"][16].digest())
            with np.load(output/"trajectory.npz",allow_pickle=False) as a:
                self.assertEqual(a["probabilities"].shape,(33,20,4))
                np.testing.assert_array_equal(a["terminal_probabilities"],result["state"].head.predict_proba(probes[0][0]))


if __name__=="__main__":
    unittest.main()
