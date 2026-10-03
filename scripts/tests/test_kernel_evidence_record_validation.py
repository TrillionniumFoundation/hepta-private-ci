"""Adversarial tests for the execution-receipt admission boundary."""

import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kernel_evidence_record_validation as validation


class ExecutionRecordTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.name = "evidence-tests.json"
        self.expected = {
            "source_sha": "a" * 40,
            "tested_sha": "a" * 40,
            "base_sha": "b" * 40,
            "lane": "source-head",
            "run_id": "100",
            "run_attempt": "2",
            "job": "source-head",
        }
        self.identity = {
            "commit": "a" * 40,
            "tree": "c" * 40,
            "parents": ["b" * 40],
            "dirty": False,
        }
        self.log = b"running 7 tests\ntest result: ok. 7 passed; 0 failed; 0 ignored;\n"
        (self.root / "execution.log").write_bytes(self.log)
        now = datetime.now(timezone.utc)
        self.record = {
            "schema_version": 1,
            **self.expected,
            "command": validation.EXPECTED_COMMANDS[self.name],
            "working_directory": str(self.root),
            "before": copy.deepcopy(self.identity),
            "after": copy.deepcopy(self.identity),
            "status": "passed",
            "error": None,
            "exit_code": 0,
            "command_exit_code": 0,
            "returncode": 0,
            "timed_out": False,
            "output_limit_exceeded": False,
            "observed_passed_tests": 7,
            "observed_failed_tests": 0,
            "started_at": (now - timedelta(seconds=1)).isoformat(),
            "finished_at": now.isoformat(),
            "elapsed_seconds": 1.0,
            "log_file": "execution.log",
            "log_bytes": len(self.log),
            "log_sha256": hashlib.sha256(self.log).hexdigest(),
        }

    def inspect(self):
        (self.root / self.name).write_text(json.dumps(self.record), encoding="utf-8")
        return validation.inspect_execution_record(
            self.root,
            self.name,
            expected=self.expected,
            identity=self.identity,
            working_directory=str(self.root),
        )

    def assert_rejected(self):
        result = self.inspect()
        self.assertFalse(result["passed"], result)
        self.assertIsNotNone(result["error"])

    def test_valid_record_binds_exact_log_bytes(self):
        result = self.inspect()
        self.assertTrue(result["passed"], result)
        self.assertEqual(
            result["log"],
            {
                "path": "execution.log",
                "present": True,
                "sha256": hashlib.sha256(self.log).hexdigest(),
                "bytes": len(self.log),
            },
        )

    def test_every_run_and_candidate_identity_is_required(self):
        original = copy.deepcopy(self.record)
        for key in self.expected:
            with self.subTest(key=key):
                self.record = copy.deepcopy(original)
                self.record[key] = "different"
                self.assert_rejected()
                self.record.pop(key)
                self.assert_rejected()

    def test_boolean_and_float_exit_codes_never_count_as_zero(self):
        original = copy.deepcopy(self.record)
        for key in (
            "exit_code",
            "command_exit_code",
            "returncode",
            "observed_failed_tests",
        ):
            for value in (False, True, 0.0, "0", None, -1, 1):
                with self.subTest(key=key, value=value):
                    self.record = copy.deepcopy(original)
                    self.record[key] = value
                    self.assert_rejected()

    def test_missing_or_failed_terminal_state_is_rejected(self):
        for status in (None, "running", "failed", "interrupted", "skipped", "success"):
            with self.subTest(status=status):
                self.record["status"] = status
                self.assert_rejected()

    def test_nonnull_error_cannot_be_covered_by_passed_status(self):
        self.record["error"] = "test execution failed"
        self.assert_rejected()

    def test_schema_requires_exact_integer_version(self):
        for value in (None, True, 1.0, 2, "1"):
            with self.subTest(value=value):
                self.record["schema_version"] = value
                self.assert_rejected()

    def test_empty_suite_and_noninteger_test_counts_are_rejected(self):
        for value in (0, False, 1.0, "7", -1, None):
            with self.subTest(value=value):
                self.record["observed_passed_tests"] = value
                self.assert_rejected()

    def test_non_test_verification_can_have_zero_test_count(self):
        self.name = "docs.json"
        self.record["command"] = validation.EXPECTED_COMMANDS[self.name]
        self.record["observed_passed_tests"] = 0
        self.assertTrue(self.inspect()["passed"])

    def test_arbitrary_successful_command_is_not_qualification(self):
        for command in (["true"], ["echo", "7 passed"], "cargo test", None):
            with self.subTest(command=command):
                self.record["command"] = command
                self.assert_rejected()

    def test_different_working_directory_is_rejected(self):
        self.record["working_directory"] = "/another/checkout"
        self.assert_rejected()

    def test_before_and_after_must_match_and_remain_clean(self):
        original = copy.deepcopy(self.record)
        for boundary in ("before", "after"):
            for field, value in (
                ("dirty", True),
                ("dirty", 0),
                ("commit", "d" * 40),
                ("tree", "d" * 40),
                ("parents", []),
            ):
                with self.subTest(boundary=boundary, field=field):
                    self.record = copy.deepcopy(original)
                    self.record[boundary][field] = value
                    self.assert_rejected()

    def test_timeout_and_output_limit_require_explicit_false(self):
        original = copy.deepcopy(self.record)
        for field in ("timed_out", "output_limit_exceeded"):
            for value in (True, 0, "false", None):
                with self.subTest(field=field, value=value):
                    self.record = copy.deepcopy(original)
                    self.record[field] = value
                    self.assert_rejected()

    def test_log_modification_is_detected_even_at_same_size(self):
        (self.root / "execution.log").write_bytes(b"x" * len(self.log))
        self.assert_rejected()

    def test_wrong_log_digest_or_length_is_rejected(self):
        original = copy.deepcopy(self.record)
        for key, value in (
            ("log_bytes", False),
            ("log_bytes", len(self.log) - 1),
            ("log_sha256", "d" * 64),
            ("log_sha256", None),
        ):
            with self.subTest(key=key, value=value):
                self.record = copy.deepcopy(original)
                self.record[key] = value
                self.assert_rejected()

    def test_missing_log_is_not_success(self):
        (self.root / "execution.log").unlink()
        self.assert_rejected()

    def test_log_paths_cannot_escape_records_directory(self):
        for value in (
            "../outside.log",
            "/tmp/outside.log",
            "a/b.log",
            r"a\b.log",
            "C:log",
            "",
            None,
            "..",
        ):
            with self.subTest(value=value):
                self.record["log_file"] = value
                self.assert_rejected()

    def test_symlink_log_is_rejected(self):
        target = self.root / "real.log"
        target.write_bytes(self.log)
        (self.root / "execution.log").unlink()
        (self.root / "execution.log").symlink_to(target)
        self.assert_rejected()

    def test_hardlinked_log_is_rejected(self):
        os.link(self.root / "execution.log", self.root / "alias.log")
        self.assert_rejected()

    def test_oversized_log_is_rejected_without_loading_it(self):
        with (self.root / "execution.log").open("wb") as stream:
            stream.truncate(validation.MAX_LOG_BYTES + 1)
        self.assert_rejected()

    def test_empty_log_is_rejected(self):
        (self.root / "execution.log").write_bytes(b"")
        self.assert_rejected()

    def test_duplicate_json_fields_are_rejected(self):
        (self.root / self.name).write_text(
            '{"status":"failed","status":"passed"}', encoding="utf-8"
        )
        result = validation.inspect_execution_record(
            self.root,
            self.name,
            expected=self.expected,
            identity=self.identity,
            working_directory=str(self.root),
        )
        self.assertFalse(result["passed"])
        self.assertIn("duplicate", result["error"])

    def test_oversized_record_is_rejected_without_loading_it(self):
        (self.root / self.name).write_bytes(b" " * (validation.MAX_RECORD_BYTES + 1))
        result = validation.inspect_execution_record(
            self.root,
            self.name,
            expected=self.expected,
            identity=self.identity,
            working_directory=str(self.root),
        )
        self.assertFalse(result["passed"])

    def test_nonfinite_duration_is_rejected(self):
        for value in (float("nan"), float("inf"), -1, False):
            with self.subTest(value=value):
                self.record["elapsed_seconds"] = value
                self.assert_rejected()

    def test_timestamps_must_be_aware_ordered_and_not_future(self):
        original = copy.deepcopy(self.record)
        for key, value in (
            ("started_at", "2026-01-01T00:00:00"),
            ("finished_at", "2000-01-01T00:00:00+00:00"),
            ("finished_at", "2999-01-01T00:00:00+00:00"),
        ):
            with self.subTest(key=key):
                self.record = copy.deepcopy(original)
                self.record[key] = value
                self.assert_rejected()

    def test_merge_requires_recomputed_tree(self):
        self.expected["lane"] = self.record["lane"] = "base-merge"
        self.assert_rejected()
        self.record["recomputed_merge_tree"] = self.identity["tree"]
        self.assertTrue(self.inspect()["passed"])

    def test_valid_input_is_not_mutated(self):
        original = copy.deepcopy(self.record)
        self.assertTrue(self.inspect()["passed"])
        self.assertEqual(self.record, original)


if __name__ == "__main__":
    unittest.main()
