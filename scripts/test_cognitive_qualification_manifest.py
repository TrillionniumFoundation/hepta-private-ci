#!/usr/bin/env python3
"""Evidence parser regressions; diagnostic retention must never become a pass."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

from cognitive_qualification_manifest import load_record
from cognitive_store_plan import spec_sha256


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "command.json"
        self.context = dict(tested_sha="1" * 40, source_sha="1" * 40, base_sha="2" * 40,
                            tested_tree="3" * 40, lane="source-head", run_id="100", run_attempt="1")
        self.log = self.path.parent / "command.log"
        self.log.write_bytes(b"test result: ok. 8 passed; 0 failed;\n")
        identity = dict(commit=self.context["tested_sha"], tree=self.context["tested_tree"], dirty=False)
        self.record = {key: value for key, value in self.context.items() if key != "tested_tree"}
        self.expected = dict(record="command.json", command=["cargo", "test", "--locked"],
                             working_directory=str(self.path.parent), minimum_tests=8,
                             timeout_seconds=1800, native=True, environment={})
        self.record.update(command=self.expected["command"],
                           working_directory=self.expected["working_directory"], timeout_seconds=1800,
                           command_spec_sha256=spec_sha256(self.expected))
        self.record.update(status="passed", command_exit_code=0, exit_code=0,
                           before=identity, after=dict(identity), log_file=self.log.name,
                           log_sha256=hashlib.sha256(self.log.read_bytes()).hexdigest(),
                           log_bytes=self.log.stat().st_size, minimum_tests=8,
                           observed_passed_tests=8, observed_failed_tests=0)

    def collect(self):
        self.path.write_text(json.dumps(self.record), encoding="utf-8")
        return load_record(self.path, self.context, self.expected)

    def test_valid_exact_record_passes(self):
        self.assertEqual(self.collect()["status"], "passed")

    def test_missing_record_is_not_executed(self):
        self.assertEqual(load_record(self.path, self.context, self.expected)["status"], "not_executed")

    def test_failed_command_is_retained(self):
        self.record.update(status="failed", command_exit_code=1, exit_code=1)
        self.assertEqual(self.collect()["status"], "failed")

    def test_skipped_or_running_record_never_passes(self):
        for status in ("running", "interrupted"):
            self.record["status"] = status
            self.assertEqual(self.collect()["status"], "incomplete")

    def test_infrastructure_skip_is_retained_as_not_executed(self):
        self.record.update(status="skipped", error="infrastructure_invalid")
        self.record.pop("log_file")
        self.assertEqual(self.collect()["status"], "not_executed")

    def test_old_run_success_is_not_reused(self):
        self.record["run_id"] = "99"
        self.assertEqual(self.collect()["status"], "evidence_invalid")

    def test_log_tampering_is_rejected(self):
        self.log.write_bytes(b"different log")
        self.assertEqual(self.collect()["status"], "evidence_invalid")

    def test_missing_log_is_not_success(self):
        self.log.unlink()
        self.assertEqual(self.collect()["status"], "evidence_invalid")

    def test_too_few_actual_tests_is_failure(self):
        self.record["observed_passed_tests"] = 0
        self.log.write_bytes(b"test result: ok. 0 passed; 0 failed;\n")
        self.record["log_bytes"] = self.log.stat().st_size
        self.record["log_sha256"] = hashlib.sha256(self.log.read_bytes()).hexdigest()
        self.assertEqual(self.collect()["status"], "failed")

    def test_dirty_after_state_is_rejected(self):
        self.record["after"]["dirty"] = True
        self.assertEqual(self.collect()["status"], "evidence_invalid")

    def test_timeout_cannot_hide_behind_zero_exit(self):
        self.record["timed_out"] = True
        self.assertEqual(self.collect()["status"], "failed")


if __name__ == "__main__":
    unittest.main()
