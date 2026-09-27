#!/usr/bin/env python3
"""Portable contract tests only; these never substitute for Rust qualification."""
from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location(
    "authbus_receipt", Path(__file__).with_name("authbus-exact-head-evidence.py")
)
assert spec is not None and spec.loader is not None
receipt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(receipt)


class ReceiptContract(unittest.TestCase):
    def setUp(self):
        self.candidate = "a" * 40
        self.rows = [{"id": name, "candidate": self.candidate, "state": "success",
                      "exit_code": 0, "log_sha256": "b" * 64,
                      "elapsed_seconds": 0.1, "passed_tests": 1}
                     for name in receipt.REQUIRED]

    def test_complete_gate_set_is_required(self):
        self.assertTrue(receipt.gates_pass(self.rows, self.candidate))
        self.assertFalse(receipt.gates_pass(self.rows[:-1], self.candidate))
        self.assertFalse(receipt.gates_pass(self.rows + [self.rows[0]], self.candidate))
        self.assertFalse(receipt.gates_pass([], self.candidate))

    def test_all_non_success_states_are_rejected(self):
        for state in ("not_run", "running", "queued", "skipped", "cancelled", "interrupted", "timeout", "failure", "deferred"):
            with self.subTest(state=state):
                rows = copy.deepcopy(self.rows)
                rows[0]["state"] = state
                self.assertFalse(receipt.gates_pass(rows, self.candidate))

    def test_different_candidate_and_exit_status_are_rejected(self):
        for field, value in (("candidate", "c" * 40), ("exit_code", 1), ("exit_code", None),
                             ("log_sha256", ""), ("log_sha256", None), ("elapsed_seconds", -1)):
            with self.subTest(field=field, value=value):
                rows = copy.deepcopy(self.rows)
                rows[0][field] = value
                self.assertFalse(receipt.gates_pass(rows, self.candidate))

    def test_zero_test_execution_is_not_qualification(self):
        for name in receipt.TEST_STEPS:
            rows = copy.deepcopy(self.rows)
            next(row for row in rows if row["id"] == name)["passed_tests"] = 0
            self.assertFalse(receipt.gates_pass(rows, self.candidate))

    def test_fixed_command_plan_covers_every_gate(self):
        self.assertEqual(set(receipt.REQUIRED), set(receipt.commands()))
        for name in receipt.TEST_STEPS:
            self.assertIn("--locked", receipt.commands()[name])
            self.assertIn("--all-targets", receipt.commands()[name])

    def test_real_subprocess_failure_is_recorded(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            row = {"id": "format", "candidate": self.candidate}
            receipt.run_step(row, [sys.executable, "-c", "print('failure fixture'); raise SystemExit(7)"],
                             directory, dict(os.environ), 5)
            self.assertEqual(row["state"], "failure")
            self.assertEqual(row["exit_code"], 7)
            self.assertEqual(row["log_sha256"], receipt.sha256(directory / "format.log"))
            self.assertEqual(json.loads((directory / "format.json").read_text())["exit_code"], 7)

    @unittest.skipUnless(os.name == "posix", "POSIX process-group test")
    def test_timeout_is_not_success(self):
        with tempfile.TemporaryDirectory() as raw:
            row = {"id": "format", "candidate": self.candidate}
            receipt.run_step(row, [sys.executable, "-c", "import time; time.sleep(10)"],
                             Path(raw), dict(os.environ), 0.05)
            self.assertEqual(row["state"], "timeout")
            self.assertIsNotNone(row["exit_code"])

    def test_zero_exit_without_test_execution_is_rejected(self):
        with tempfile.TemporaryDirectory() as raw:
            row = {"id": "authbus", "candidate": self.candidate}
            receipt.run_step(row, [sys.executable, "-c", "print('no test execution')"],
                             Path(raw), dict(os.environ), 5)
            self.assertEqual(row["state"], "failure")
            self.assertEqual(row["passed_tests"], 0)

    def test_unreferenced_old_binaries_do_not_count(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target = root / "target"
            target.mkdir()
            (target / "old-authbus-test").write_bytes(b"old artifact")
            self.assertEqual(receipt.executable_evidence(root, target), [])

    def test_outside_target_artifact_is_rejected(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target = root / "target"
            target.mkdir()
            outside = root / "outside"
            outside.write_bytes(b"fixture, not a compiler product")
            (root / "authbus.log").write_text(json.dumps({
                "reason": "compiler-artifact", "profile": {"test": True},
                "executable": str(outside),
            }) + "\n")
            with self.assertRaises(ValueError):
                receipt.executable_evidence(root, target)


if __name__ == "__main__":
    unittest.main(verbosity=2)
