"""Actual nonlinear V5 audit fixtures and state/action/projection faults."""

import json
from pathlib import Path
import shutil
import tempfile
import unittest

import numpy as np

from cell_field_action_io import save_arrays, write_json
from cell_field_experiments_v5 import fixed_anchor, pressure_census
from cell_field_policy_v5 import POLICIES, execute_policy
from cell_field_replay_v5 import _fixed, _policy, _pressure
from cell_field_run_v5 import save_policy
from test_cell_field_planner_v5 import configuration, fixture


def protocol():
    return {"h":.02,"anchor_offsets":[0,8,16],"policy_configuration":configuration(32),
        "models":["loss2","q4","history4","structured4","full","analytic","response_svd"],
        "response":{"impulse_compression_relative_tolerance":1e-6},
        "fixed_scoring":{"dt":.02,"effort_price":.1,"direct_coefficient":.03,"current_shift":.03,"feasibility_tolerance":1e-9},
        "pressure":{"max_search_steps":64,"models":["adjoint","loss2"],"budgets":[.25,1.,4.],
                    "hard_retention":[False,True],"backtracking":[1.,.5,.25,.125,0.]}}


class V5ReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.state,cls.split,cls.anchor = fixture("gated")
        cls.projected = np.vstack([cls.split[r][0] for r in ("old_train","current_train")])
        cls.expected = {"expected_bindings":cls.state.bindings,"expected_protocol":cls.state.protocol,
                        "expected_contexts":cls.state.contexts}
        cls.plan = protocol()
        for policy in POLICIES:
            result = execute_policy(cls.state,cls.split,cls.anchor,policy,cls.plan["policy_configuration"])
            if result["record"]["status"] != "completed":
                raise AssertionError(result["record"])
            save_policy(result,cls.projected,cls.root/policy)
        fixed_anchor(cls.state,cls.split,cls.plan,cls.projected,np.arange(8),cls.anchor,cls.root/"fixed")

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def check_policy(self,path,policy):
        return _policy(path,self.state,self.expected,self.split,self.projected,self.plan,self.anchor,policy)

    def test_all_six_policies_replay_and_candidate_restores_replans_midpoint(self):
        for policy in POLICIES:
            result = self.check_policy(self.root/policy,policy)
            self.assertEqual(result["status"],"passed")
            self.assertEqual(result["replayed_optimizer_steps"],32)
            if policy == "response_h8_guarded":
                self.assertEqual(result["midpoint_replan"],"passed")
                self.assertEqual(result["restored_suffix_steps"],16)
                self.assertTrue(all(v == 0 for v in result["midpoint_max_errors"].values()))

    def test_changed_action_or_sampler_metadata_is_rejected(self):
        for fault in ("action","sampler","recorded_error"):
            with tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary)/"policy"
                shutil.copytree(self.root/"response_h8_guarded",path)
                if fault == "action":
                    with np.load(path/"trajectory.npz",allow_pickle=False) as a:
                        values = {k:a[k] for k in a.files}
                    values["actions"][17,0] += 1e-5
                    save_arrays(path/"trajectory.npz",values)
                elif fault == "sampler":
                    filename = path/"midpoint/manifest.json"
                    metadata = json.loads(filename.read_bytes())
                    metadata["rng"]["state"]["state"] ^= 1
                    write_json(filename,metadata)
                else:
                    filename = path/"result.json"
                    record = json.loads(filename.read_bytes())
                    record["steps"][-1]["error"] = {"type":"RuntimeError","message":"actual execution error must block audit"}
                    write_json(filename,record)
                with self.assertRaises(ValueError):
                    self.check_policy(path,"response_h8_guarded")

    def test_seven_prediction_models_and_every_nonlinear_fixed_branch_replay(self):
        result = _fixed(self.root/"fixed",self.state,self.expected,self.split,self.plan,self.anchor)
        self.assertEqual(result["branches"],49)
        self.assertEqual(result["replayed_optimizer_steps"],392)
        self.assertEqual(result["analytic_map_error"],0.)

    def test_intermediate_nonlinear_state_and_svd_tensor_faults_reject(self):
        for filename,key in (("actual_trajectories.npz","states"),("response.npz","coefficients")):
            with tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary)/"fixed"
                shutil.copytree(self.root/"fixed",path)
                with np.load(path/filename,allow_pickle=False) as a:
                    values = {k:a[k] for k in a.files}
                if key == "states":
                    values[key][3,4,0] += 1e-5
                else:
                    values[key][1,0,0] += 1e-5
                save_arrays(path/filename,values)
                with self.assertRaises(ValueError):
                    _fixed(path,self.state,self.expected,self.split,self.plan,self.anchor)

    def test_real_pressure_census_rechecks_certifications_and_unavailable_conditions(self):
        state,split,anchor = fixture("linear",conflict=True)
        expected = {"expected_bindings":state.bindings,"expected_protocol":state.protocol,
                    "expected_contexts":state.contexts}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/"pressure"
            pressure_census(state,split,self.plan,self.projected,np.arange(8),path)
            result = _pressure(path,state,expected,split,self.projected,self.plan,anchor,np.arange(8))
            self.assertEqual(result["status"],"passed")
            self.assertEqual(result["instantiated_slots"],26)
            self.assertGreater(result["verified_optimizer_steps"],0)
            filename = path/"prevention/frozen_plans.json"
            frozen = json.loads(filename.read_bytes())
            frozen["plans"][1]["id"] = frozen["plans"][2]["id"]
            write_json(filename,frozen)
            with self.assertRaisesRegex(ValueError,"pressure candidate census"):
                _pressure(path,state,expected,split,self.projected,self.plan,anchor,np.arange(8))


if __name__ == "__main__":
    unittest.main()
