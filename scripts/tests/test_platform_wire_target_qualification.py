"""Synthetic record-validation tests, never target-host qualification receipts."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import platform_wire_target_qualification as target


class TargetCommandEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.argv = ["fixture-runner", "--tests"]
        self.subject = {
            "source_sha": "a" * 40, "tested_sha": "a" * 40,
            "tested_tree": "b" * 40, "tested_parents": ["c" * 40],
            "run_id": "123", "run_attempt": "2", "lane": "source-head",
        }
        identity = {
            "commit": self.subject["tested_sha"], "tree": self.subject["tested_tree"],
            "parents": self.subject["tested_parents"], "dirty": False,
        }
        self.log = b"test result: ok. 3 passed; 0 failed; 0 ignored;\n"
        self.record = {
            "schema_version": 1, "status": "passed", "command": self.argv,
            "command_exit_code": 0, "exit_code": 0, "returncode": 0,
            "observed_failed_tests": 0, "observed_passed_tests": 3,
            "minimum_tests": 3, "timed_out": False, "output_limit_exceeded": False,
            "before": copy.deepcopy(identity), "after": copy.deepcopy(identity),
            "log_file": "command.log", "log_bytes": len(self.log),
            "log_sha256": hashlib.sha256(self.log).hexdigest(),
            **{key: self.subject[key] for key in (
                "source_sha", "tested_sha", "run_id", "run_attempt", "lane",
            )},
        }
        (self.root / "command.log").write_bytes(self.log)

    def verify(self, record: dict | None = None) -> dict:
        (self.root / "command.json").write_text(json.dumps(record or self.record))
        return target.verify_command(self.root, "command", 3, self.argv, self.subject)

    def test_valid_record_binds_raw_log_and_test_count(self) -> None:
        result = self.verify()
        self.assertEqual(result["observed_passed_tests"], 3)
        self.assertEqual(result["log_sha256"], hashlib.sha256(self.log).hexdigest())

    def test_nonpassing_states_reject(self) -> None:
        for state in ("running", "failed", "skipped", "cancelled", "rejected", None):
            with self.subTest(state=state), self.assertRaises(ValueError):
                self.verify({**self.record, "status": state})

    def test_boolean_or_nonzero_exit_fields_reject(self) -> None:
        for field in ("command_exit_code", "exit_code", "returncode", "observed_failed_tests"):
            for value in (False, True, 1, -1, None):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    self.verify({**self.record, field: value})

    def test_execution_limit_flags_reject(self) -> None:
        for field in ("timed_out", "output_limit_exceeded"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.verify({**self.record, field: True})

    def test_stale_source_run_attempt_or_lane_rejects(self) -> None:
        for field in ("source_sha", "tested_sha", "run_id", "run_attempt", "lane"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.verify({**self.record, field: "other"})

    def test_changed_command_or_floor_rejects(self) -> None:
        for field, value in (("command", ["true"]), ("minimum_tests", 2)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.verify({**self.record, field: value})

    def test_dirty_changed_tree_or_parents_reject(self) -> None:
        for field, value in (("dirty", True), ("tree", "d" * 40), ("parents", [])):
            record = copy.deepcopy(self.record)
            record["before"][field] = value
            record["after"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.verify(record)

    def test_source_mutation_during_command_rejects(self) -> None:
        record = copy.deepcopy(self.record)
        record["after"]["commit"] = "d" * 40
        with self.assertRaises(ValueError):
            self.verify(record)

    def test_counters_require_raw_log_evidence(self) -> None:
        with self.assertRaisesRegex(ValueError, "test counts"):
            self.verify({**self.record, "observed_passed_tests": 4})

    def test_zero_tests_cannot_meet_floor(self) -> None:
        with self.assertRaises(ValueError):
            self.verify({**self.record, "observed_passed_tests": 0})

    def test_log_mutation_or_truncation_rejects(self) -> None:
        (self.root / "command.log").write_bytes(self.log[:-1])
        with self.assertRaises(ValueError):
            self.verify()

    def test_path_traversal_and_symlinks_reject(self) -> None:
        for name in ("../command.log", "/tmp/command.log", "", ".", "..", None):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.verify({**self.record, "log_file": name})
        (self.root / "alias.log").symlink_to(self.root / "command.log")
        with self.assertRaises(ValueError):
            self.verify({**self.record, "log_file": "alias.log"})

    def test_oversize_evidence_rejects(self) -> None:
        with self.assertRaises(ValueError):
            target.read_local(self.root, "command.log", len(self.log) - 1)

    def test_duplicate_record_fields_reject(self) -> None:
        raw = json.dumps(self.record)
        (self.root / "command.json").write_text(raw[:-1] + ',"status":"passed"}')
        with self.assertRaises(ValueError):
            target.verify_command(self.root, "command", 3, self.argv, self.subject)

    def test_boolean_schema_and_counts_reject(self) -> None:
        for field in ("schema_version", "minimum_tests", "log_bytes", "observed_passed_tests"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.verify({**self.record, field: True})

    def test_failed_setup_retains_nonpassing_receipt(self) -> None:
        # All execution records and measurements are absent. Even an otherwise
        # well-shaped workflow identity cannot manufacture a passing receipt.
        def fake_git(*args: str) -> str:
            if args == ("rev-parse", "HEAD"):
                return "a" * 40
            if args[0] == "rev-parse":
                return "b" * 40
            if args[0] == "show":
                return "c" * 40
            return ""

        env = {
            "GITHUB_SHA": "a" * 40, "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "2",
            "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REPOSITORY": "fixture/repo",
            "GITHUB_WORKFLOW_REF": "fixture/repo/.github/workflows/platform-wire-target-host.yml@refs/heads/test",
            "GITHUB_WORKFLOW_SHA": "a" * 40, "GITHUB_WORKFLOW": "fixture",
            "RUNNER_NAME": "fixture", "RUNNER_OS": "Linux", "RUNNER_ARCH": "X64",
            "RUSTUP_TOOLCHAIN": "fixture",
        }
        with patch.object(target, "git", side_effect=fake_git), patch.dict(target.os.environ, env):
            self.assertEqual(target.receipt(self.root, "a" * 40, "failure", "skipped"), 1)
        receipt = json.loads((self.root / "platform-wire-target-host.json").read_text())
        self.assertEqual(receipt["status"], "infrastructure_invalid")
        self.assertTrue(receipt["errors"])
        self.assertEqual(receipt["command_records"], {})
        for flag in ("independent_acceptance", "activation", "release", "authenticated_network_ingress"):
            self.assertIs(receipt[flag], False)


if __name__ == "__main__":
    unittest.main()
