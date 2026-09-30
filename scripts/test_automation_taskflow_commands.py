"""Protocol tests, not fabricated command or native execution receipts."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.automation_taskflow_commands import PLAN, persist_summary, validate_record


class ActualCommandRecordTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        log = b"test fixture log, not a real test runner result\n"
        (self.root / "record.log").write_bytes(log)
        self.commit, self.tree = "1" * 40, "2" * 40
        self.argv = ["example-test-runner", "--locked"]
        identity = {"commit": self.commit, "tree": self.tree, "parents": [], "dirty": False}
        self.record = {
            "status": "passed",
            "exit_code": 0,
            "command_exit_code": 0,
            "command": self.argv,
            "tested_sha": self.commit,
            "before": identity,
            "after": copy.deepcopy(identity),
            "timed_out": False,
            "output_limit_exceeded": False,
            "observed_failed_tests": 0,
            "observed_passed_tests": 4,
            "minimum_tests": 4,
            "working_directory": "/fixture/codex-rs",
            "started_at": "2026-09-27T00:00:00+00:00",
            "finished_at": "2026-09-27T00:00:01+00:00",
            "elapsed_seconds": 1.0,
            "log_file": "record.log",
            "log_sha256": hashlib.sha256(log).hexdigest(),
        }

    def valid(self) -> bool:
        return validate_record(
            self.record,
            self.argv,
            self.commit,
            self.root,
            4,
            expected_tree=self.tree,
            working_directory="/fixture/codex-rs",
        )

    def test_coherent_fixture_is_accepted_by_protocol_only(self) -> None:
        self.assertTrue(self.valid())

    def test_every_nonterminal_or_negative_status_is_rejected(self) -> None:
        for status in (None, "running", "not_run", "failed", "rejected", "interrupted", "skipped", "queued"):
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
        for field, value in (
            ("timed_out", True),
            ("output_limit_exceeded", True),
            ("exit_code", 1),
            ("command_exit_code", 1),
            ("observed_failed_tests", 1),
        ):
            with self.subTest(field=field):
                old = self.record[field]
                self.record[field] = value
                self.assertFalse(self.valid())
                self.record[field] = old

    def test_plan_retains_exact_owner_native_product_and_recovery_gates(self) -> None:
        names = [row[0] for row in PLAN]
        self.assertEqual(len(names), len(set(names)))
        required = {
            "lane-b-path-self-test",
            "lane-b-path",
            "contract",
            "format",
            "compile",
            "clippy",
            "migration",
            "product",
            "bazel",
            "scheduler-review",
            "recovery-review",
            "rust-toolchain",
            "cargo-toolchain",
            "durable-circuit",
            "durable-circuit-recovery",
            "taskflow-bounded-startup",
            "runtime-crash-points",
            "runtime-property-sweep",
            "multi-scheduler",
            "timer-fence",
            "cross-host-contract",
        }
        self.assertTrue(required.issubset(names))
        for _, _, argv, _, _ in PLAN:
            self.assertNotEqual(argv, ["true"])
            self.assertNotIn("--fix", argv)
            self.assertNotIn("push", argv)
            self.assertNotIn("commit", argv)
        python = next(row for row in PLAN if row[0] == "python")
        self.assertIn("scripts.test_automation_taskflow_checkpoint", python[2])
        self.assertGreaterEqual(python[3], 76)
        for name in required - {"contract", "format", "compile", "clippy", "bazel", "rust-toolchain", "cargo-toolchain", "lane-b-path", "lane-b-path-self-test"}:
            row = next(row for row in PLAN if row[0] == name)
            self.assertGreaterEqual(row[3], 1)

    def test_coherently_wrong_tree_is_rejected(self) -> None:
        self.record["before"]["tree"] = "3" * 40
        self.record["after"]["tree"] = "3" * 40
        self.assertFalse(self.valid())

    def test_wrong_working_directory_is_rejected(self) -> None:
        self.record["working_directory"] = "/different/checkout/codex-rs"
        self.assertFalse(self.valid())

    def test_missing_time_or_negative_duration_is_rejected(self) -> None:
        for field, value in (
            ("started_at", None),
            ("finished_at", "invalid"),
            ("elapsed_seconds", float("nan")),
            ("elapsed_seconds", -1),
            ("finished_at", "2026-09-26T00:00:00+00:00"),
            ("started_at", "2026-09-27T00:00:00"),
        ):
            old = self.record[field]
            self.record[field] = value
            self.assertFalse(self.valid())
            self.record[field] = old

    def test_boolean_numbers_and_changed_minimum_rejected(self) -> None:
        for field in (
            "exit_code",
            "command_exit_code",
            "observed_passed_tests",
            "observed_failed_tests",
            "minimum_tests",
        ):
            old = self.record[field]
            self.record[field] = False
            self.assertFalse(self.valid())
            self.record[field] = old
        self.record["minimum_tests"] = 0
        self.assertFalse(self.valid())

    def test_summary_persistence_keeps_not_run_as_not_run(self) -> None:
        path = self.root / "summary.json"
        state = {"status": "running", "commands": [{"id": "compile", "status": "not_run"}]}
        persist_summary(path, state)
        self.assertEqual(json.loads(path.read_text()), state)
        state["status"] = "failed"
        persist_summary(path, state)
        self.assertEqual(json.loads(path.read_text()), state)
        self.assertEqual(sorted(path.name for path in self.root.iterdir()), ["record.log", "summary.json"])


if __name__ == "__main__":
    unittest.main()
