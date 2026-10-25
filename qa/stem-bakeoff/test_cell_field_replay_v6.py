"""Actual V6 replay fixtures with independent coefficient and receipt faults."""

import json
from pathlib import Path
import shutil
import tempfile
import unittest

import numpy as np

from cell_field_action_io import save_arrays,write_json
from cell_field_experiments_v6 import fixed_anchor,pressure_census
from cell_field_policy_v6 import POLICIES,execute_policy
from cell_field_replay_v6 import _fixed,_policy,_pressure
from cell_field_run_v6 import save_policy
from test_cell_field_planner_v5 import fixture
from test_cell_field_replay_v5 import protocol


class V6ReplayTests(unittest.TestCase):
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

    def test_all_six_policies_repair_replay_and_candidate_full_midpoint_replan(self):
        for policy in POLICIES:
            result = self.check_policy(self.root/policy,policy)
            self.assertEqual(result["status"],"passed")
            self.assertEqual(result["replayed_optimizer_steps"],32)
            if policy == "future_field_h8_repaired":
                self.assertEqual(result["midpoint_replan"],"passed")
                self.assertEqual(result["restored_suffix_steps"],16)
                self.assertEqual(result["verified_blocks"],4)
                self.assertTrue(all(v == 0 for v in result["midpoint_max_errors"].values()))

    def test_all_fixed_nonlinear_branches_and_independent_forward_field(self):
        result = _fixed(self.root/"fixed",self.state,self.expected,self.split,self.plan,self.anchor)
        self.assertEqual(result["branches"],49)
        self.assertEqual(result["replayed_optimizer_steps"],392)
        self.assertLess(result["future_field"]["coefficient_relative_error"],2e-11)

    def test_altered_field_coefficients_with_consistent_file_commitment_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(self.root/"fixed",root/"fixed")
            for extension in (".npz",".json"):
                shutil.copyfile(self.root/("fixed-future-field"+extension),root/("fixed-future-field"+extension))
            path = root/"fixed-future-field.npz"
            with np.load(path,allow_pickle=False) as a:
                arrays = {k:a[k] for k in a.files}
            arrays["field_observations"][0,5,0] += .001
            save_arrays(path,arrays)
            from cell_field_features import file_hash
            record = json.loads(path.with_suffix(".json").read_bytes())
            record["predictions_sha256"] = file_hash(path)
            write_json(path.with_suffix(".json"),record)
            with self.assertRaisesRegex(ValueError,"independent forward field coefficients"):
                _fixed(root/"fixed",self.state,self.expected,self.split,self.plan,self.anchor)

    def test_changed_action_hidden_execution_error_and_repair_accounting_reject(self):
        for fault in ("action","nested_error","trial_count","midpoint_rng"):
            with tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary)/"policy"
                shutil.copytree(self.root/"future_field_h8_repaired",path)
                if fault == "action":
                    with np.load(path/"trajectory.npz",allow_pickle=False) as a:
                        values = {k:a[k] for k in a.files}
                    values["actions"][17,0] += 1e-5
                    save_arrays(path/"trajectory.npz",values)
                elif fault == "midpoint_rng":
                    filename = path/"midpoint/manifest.json"
                    metadata = json.loads(filename.read_bytes())
                    metadata["rng"]["state"]["state"] ^= 1
                    write_json(filename,metadata)
                else:
                    filename = path/"result.json"
                    record = json.loads(filename.read_bytes())
                    repair = record["steps"][0]["repair"]
                    if fault == "nested_error":
                        repair["step_records"][0]["error"] = {"type":"Injected","message":"actual failure"}
                    else:
                        repair["probe_head_evaluations"] += 1
                    write_json(filename,record)
                with self.assertRaises(ValueError):
                    self.check_policy(path,"future_field_h8_repaired")

    def test_paired_pressure_guard_and_repair_exact_replay_and_slot_census(self):
        state,split,anchor = fixture("linear",conflict=True)
        expected = {"expected_bindings":state.bindings,"expected_protocol":state.protocol,
                    "expected_contexts":state.contexts}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/"pressure"
            pressure_census(state,split,self.plan,self.projected,np.arange(8),path)
            result = _pressure(path,state,expected,split,self.projected,self.plan,anchor,np.arange(8))
            for method in ("guarded","repaired"):
                self.assertEqual(result[method]["instantiated_slots"],26)
                self.assertGreater(result[method]["verified_optimizer_steps"],0)
            filename = path/"prevention/frozen_plans.json"
            frozen = json.loads(filename.read_bytes())
            frozen["plans"][1]["id"] = frozen["plans"][2]["id"]
            write_json(filename,frozen)
            with self.assertRaisesRegex(ValueError,"pressure candidate census"):
                _pressure(path,state,expected,split,self.projected,self.plan,anchor,np.arange(8))


if __name__ == "__main__":
    unittest.main()
