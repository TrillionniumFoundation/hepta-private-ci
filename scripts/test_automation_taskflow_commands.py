"""Protocol tests, not fabricated command or native execution receipts."""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import tempfile
import unittest

from scripts.automation_taskflow_commands import PLAN, validate_record


class ActualCommandRecordTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        log = b"test fixture log, not a real test runner result\n"
        (self.root / "record.log").write_bytes(log)
        self.commit = "1" * 40
        self.argv = ["example-test-runner", "--locked"]
        identity = {"commit": self.commit, "tree": "2" * 40, "parents": [], "dirty": False}
        self.record = {
            "status": "passed", "exit_code": 0, "command_exit_code": 0,
            "command": self.argv, "tested_sha": self.commit,
            "before": identity, "after": copy.deepcopy(identity),
            "timed_out": False, "output_limit_exceeded": False,
            "observed_failed_tests": 0, "observed_passed_tests": 4,
            "log_file": "record.log", "log_sha256": hashlib.sha256(log).hexdigest(),
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def valid(self) -> bool:
        return validate_record(self.record, self.argv, self.commit, self.root, 4)

    def test_coherent_fixture_is_accepted_by_protocol_only(self) -> None:
        self.assertTrue(self.valid())

    def test_every_nonterminal_or_negative_status_is_rejected(self) -> None:
        for status in (None, "running", "not_run", "failed", "rejected", "interrupted"):
            with self.subTest(status=status):
                self.record["status"] = status
                self.assertFalse(self.valid())

    def test_changed_source_or_dirty_source_is_rejected(self) -> None:
        self.record["after"]["tree"] = "3" * 40
        self.assertFalse(self.valid())
        self.record["after"] = copy.deepcopy(self.record["before"])
        self.record["before"]["dirty"] = True
        self.record["after"]["dirty"] = True
        self.assertFalse(self.valid())

    def test_wrong_command_or_commit_is_rejected(self) -> None:
        self.record["command"] = ["true"]
        self.assertFalse(self.valid())
        self.record["command"] = self.argv
        self.record["tested_sha"] = "0" * 40
        self.assertFalse(self.valid())

    def test_missing_truncated_or_changed_log_is_rejected(self) -> None:
        (self.root / "record.log").write_bytes(b"changed")
        self.assertFalse(self.valid())
        (self.root / "record.log").unlink()
        self.assertFalse(self.valid())

    def test_log_path_cannot_escape_evidence_directory(self) -> None:
        self.record["log_file"] = "../record.log"
        self.assertFalse(self.valid())

    def test_zero_test_filtered_success_does_not_satisfy_native_minimum(self) -> None:
        self.record["observed_passed_tests"] = 0
        self.assertFalse(self.valid())

    def test_timeout_failure_and_overflow_never_become_success(self) -> None:
        for field, value in (("timed_out", True), ("output_limit_exceeded", True),
                             ("exit_code", 1), ("command_exit_code", 1),
                             ("observed_failed_tests", 1)):
            with self.subTest(field=field):
                old = self.record[field]
                self.record[field] = value
                self.assertFalse(self.valid())
                self.record[field] = old

    def test_plan_retains_native_product_migration_and_bazel_gates(self) -> None:
        names = [row[0] for row in PLAN]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue({"contract", "format", "compile", "clippy", "migration", "product",
                         "bazel", "scheduler-review", "recovery-review"}.issubset(names))
        for _, _, argv, _, _ in PLAN:
            self.assertNotEqual(argv, ["true"])
            self.assertNotIn("--fix", argv)
            self.assertNotIn("push", argv)


if __name__ == "__main__":
    unittest.main()
