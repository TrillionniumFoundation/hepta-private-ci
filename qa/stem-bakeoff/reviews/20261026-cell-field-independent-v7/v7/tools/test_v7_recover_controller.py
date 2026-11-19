"""Actual Adam prefixes with committed controller bytes and altered preimages."""

from pathlib import Path
import tempfile
import unittest

import numpy as np

from test_v7_postrun_audit import physical_fixture
from cell_field_development_artifacts_v7 import save_result
from v7_audit_records import array_hash, digest, losses, read
from v7_recover_controller import recover_case


class ControllerRecoveryTests(unittest.TestCase):
    def run_fixture(self, count, change_intended=False, wrong_plan=False):
        initial, inputs, anchors, config, identity, result = physical_fixture(count)
        intended = np.full((8, initial.parameter_count), .01)
        if change_intended:
            terminal = result["controllers"][-1]
            terminal.update(intended_actions=intended.tolist(), intended_plan_sha256=array_hash(intended))
        expected = digest(result["controllers"][-1])
        with tempfile.TemporaryDirectory() as temporary:
            path, output = Path(temporary)/"case", Path(temporary)/"recovery"
            save_result(path, {"fit_id": "fixture"}, initial, inputs, anchors, "future_field_h8", config,
                result, {"cpu_ns": 30000, "wall_ns": 40000}, losses(initial, inputs["selection"]["old"]),
                controller_identity=identity)
            before = (path/"trace.json.gz").read_bytes()
            calls = []
            def planner(state, *args, **kwargs):
                calls.append((state.digest(), kwargs["horizon"]))
                return {"record": {"status": "qualified", "cpu_ns": 9999999},
                    "actions": intended*2 if wrong_plan else intended}
            row = recover_case(path, initial, inputs, config, "future_field_h8", "a"*64, "b"*64,
                output, planner=planner)
            self.assertEqual((path/"trace.json.gz").read_bytes(), before)
            self.assertEqual(len(calls), row["planner_calls"])
            if row["status"] == "recovered_exact_original_preimage":
                saved = read(output/"controller.json")
                self.assertEqual(digest(saved), expected)
                self.assertEqual(saved["counters"]["controller_cpu_ns"], 10000)
                self.assertEqual(saved["failure_ledger"][0]["paid_wall_ns"], 20000)
            else:
                self.assertFalse((output/"controller.json").exists())
            return row

    def test_resolved_and_retained_exact_hash_recoveries_need_no_planner(self):
        for count, method in ((8, "resolved_equals_intended_hash_proof"), (24, "retained_same_plan_intended_bytes")):
            row = self.run_fixture(count)
            self.assertEqual((row["status"], row["method"], row["planner_calls"]),
                ("recovered_exact_original_preimage", method, 0))

    def test_one_planner_reconstructs_only_missing_intended_actions_and_keeps_paid_ledger(self):
        row = self.run_fixture(8, change_intended=True)
        self.assertEqual((row["status"], row["planner_calls"]), ("recovered_exact_original_preimage", 1))
        self.assertEqual([attempt["matched"] for attempt in row["attempts"]], [False, True])

    def test_hash_mismatch_is_explicit_and_no_preimage_is_written(self):
        row = self.run_fixture(8, change_intended=True, wrong_plan=True)
        self.assertEqual((row["status"], row["planner_calls"]), ("unresolved", 1))
        self.assertEqual([attempt["matched"] for attempt in row["attempts"]], [False, False])


if __name__ == "__main__":
    unittest.main()
