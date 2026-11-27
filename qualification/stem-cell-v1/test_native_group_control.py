import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from native_group_control import (BINDINGS, Q32, build_control_request, control_wire,
                                  reference_control_receipt, run_native_control)


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def fixture(**updates):
    values = dict(bindings={key: digest(key) for key in BINDINGS}, generation=3, as_of_ns=100,
        critic_cutoff_ns=80, observed_through_ns=90, expires_at_ns=10**18,
        stop_upper=.2, minimum_margin=0, remaining_formula_work=100, remaining_wall_ns=10**10,
        scenarios=[dict(probability=1, continue_lower=.8, discount=1, compute_cost=.01, time_cost=.01,
                        formula_work_upper=10, duration_upper_ns=1_000_000)])
    values.update(updates)
    return build_control_request(**values)


class NativeGroupControlOracleTests(unittest.TestCase):
    def test_observable_bindings_are_complete_and_no_labels_enter(self):
        request = fixture()
        baseline = reference_control_receipt(request)
        self.assertTrue(baseline["continue_computation"])
        for key in BINDINGS:
            changed = copy.deepcopy(request)
            changed["bindings"][key] = digest("changed-" + key)
            receipt = reference_control_receipt(changed)
            self.assertNotEqual(receipt["input_sha256"], baseline["input_sha256"])
            self.assertNotEqual(receipt["scenarios"][0]["evidence_sha256"], baseline["scenarios"][0]["evidence_sha256"])
        request["target"] = 1
        with self.assertRaises(ValueError):
            control_wire(request)

    def test_lower_rounding_negative_values_projection_and_zero_mass(self):
        request = fixture(stop_upper=-1)
        scenario = request["scenarios"][0]
        scenario.update(continue_lower_q32=-3, discount_q32=Q32 // 2, compute_cost_q32=0, time_cost_q32=0)
        receipt = reference_control_receipt(request)
        self.assertEqual(receipt["expected_lower_q32"], -2)
        scenario["continue_lower_q32"] = 3
        receipt = reference_control_receipt(request)
        self.assertEqual((receipt["scenarios"][0]["native_value_q32"], receipt["expected_lower_q32"]), (2, 1))
        request = fixture(lower=-1, upper=1)
        scenario = request["scenarios"][0]
        scenario.update(continue_lower_q32=-Q32, discount_q32=Q32, compute_cost_q32=Q32 // 2, time_cost_q32=0)
        receipt = reference_control_receipt(request)
        self.assertFalse(receipt["continue_computation"])
        self.assertEqual(receipt["reason"], "scenario_projection_unsupported")
        request = fixture()
        ignored = copy.deepcopy(request["scenarios"][0])
        ignored.update(probability_q32=0, formula_work_upper=1000, duration_upper_ns=10**12)
        request["scenarios"].append(ignored)
        self.assertTrue(reference_control_receipt(request)["continue_computation"])

    def test_mass_future_observations_unknown_fields_and_expense_fail_closed(self):
        for updates in (dict(observed_through_ns=101), dict(critic_cutoff_ns=100, observed_through_ns=100),
                        dict(generation=0), dict(minimum_margin=-1e-12)):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                fixture(**updates)
        request = fixture()
        request["scenarios"][0]["probability_q32"] -= 1
        result = run_native_control(request, "/missing/binary", clock=lambda:100)
        self.assertFalse(result["continue_computation"])
        self.assertFalse(result["native_executed"])
        self.assertFalse(reference_control_receipt(fixture(remaining_formula_work=1))["continue_computation"])

    def test_receipt_tampering_staleness_and_native_failure_stop(self):
        request = fixture()
        path = Path(__file__)
        output = reference_control_receipt(request)
        output["continue_computation"] = False
        completed = subprocess.CompletedProcess([str(path)], 0, json.dumps(output).encode(), b"")
        with patch("native_group_control.subprocess.run", return_value=completed):
            result = run_native_control(request, path, clock=lambda:100)
        self.assertEqual(result["reason"], "native_control_failed")
        self.assertFalse(result["continue_computation"])
        self.assertFalse(result["reference_match"])
        self.assertFalse(run_native_control(request, path, clock=lambda:99)["native_executed"])
        self.assertFalse(run_native_control(request, "/missing/binary", clock=lambda:100)["continue_computation"])


@unittest.skipUnless(os.environ.get("HEPTA_NDU_GROUP_CONTROL_BINARY"), "native control binary not supplied")
class ExecutedNativeGroupControlTests(unittest.TestCase):
    def test_actual_native_decisions_match_oracle_and_report_child_cost(self):
        binary = os.environ["HEPTA_NDU_GROUP_CONTROL_BINARY"]
        negative = fixture(stop_upper=-1)
        negative["scenarios"][0].update(continue_lower_q32=-3, discount_q32=Q32 // 2,
                                        compute_cost_q32=0, time_cost_q32=0)
        projected = fixture(lower=-1, upper=1)
        projected["scenarios"][0].update(continue_lower_q32=-Q32, discount_q32=Q32,
                                         compute_cost_q32=Q32 // 2, time_cost_q32=0)
        zero_mass = fixture()
        ignored = copy.deepcopy(zero_mass["scenarios"][0])
        ignored.update(probability_q32=0, duration_upper_ns=10**12)
        zero_mass["scenarios"].append(ignored)
        mixed = fixture(stop_upper=-1)
        mixed["scenarios"][0].update(probability_q32=Q32 // 2, continue_lower_q32=-3,
                                     discount_q32=Q32 // 2, compute_cost_q32=0, time_cost_q32=0)
        alternative = copy.deepcopy(mixed["scenarios"][0])
        alternative["continue_lower_q32"] = 3
        mixed["scenarios"].append(alternative)
        for request in (fixture(), fixture(stop_upper=.99), fixture(remaining_formula_work=1),
                        negative, projected, zero_mass, mixed):
            with self.subTest(stop=request["stop_upper_q32"]):
                result = run_native_control(request, binary, clock=lambda:100)
                self.assertTrue(result["reference_match"])
                self.assertEqual(result["native_receipt"], reference_control_receipt(request))
                self.assertGreater(result["child_wall_ns"], 0)
                self.assertGreaterEqual(result["native_subprocess_elapsed_ns"], result["child_wall_ns"])
                self.assertEqual(result["native_binary_sha256"], hashlib.sha256(Path(binary).read_bytes()).hexdigest())
        for wire in (control_wire(fixture()).replace(b"scenario ", b"unknown ", 1), b"x" * 16_385):
            failed = subprocess.run([binary], input=wire, capture_output=True, timeout=5)
            self.assertNotEqual(failed.returncode, 0)
            self.assertEqual(failed.stdout, b"")


if __name__ == "__main__":
    unittest.main()
