"""Local collector tests; these are not runtime or production receipts."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/control_engineering_candidate_evidence.py"
SPEC = importlib.util.spec_from_file_location("ce_candidate_collector_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)


class CandidateEvidenceCollectorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.output = self.root / "output"

    def tearDown(self):
        self.temporary.cleanup()

    def command(self, label, code, timeout=5):
        result = collector.run_command(
            self.root, self.output, label, [sys.executable, "-c", code],
            dict(os.environ), timeout_seconds=timeout,
        )
        log = self.output / result["logFile"]
        self.assertEqual(result["logSha256"], hashlib.sha256(log.read_bytes()).hexdigest())
        self.assertEqual(result["logBytes"], log.stat().st_size)
        return result

    def test_success_has_exact_log_digest(self):
        result = self.command("success", "print('fixture output')")
        self.assertEqual(result["exitCode"], 0)
        self.assertEqual(result["status"], "passed")
        self.assertFalse(result["timedOut"])

    def test_nonzero_exit_is_never_relabelled_as_success(self):
        result = self.command("failed", "raise SystemExit(7)")
        self.assertEqual(result["exitCode"], 7)
        self.assertEqual(result["status"], "failed")

    def test_timeout_retains_failure(self):
        result = self.command("timeout", "import time; time.sleep(5)", timeout=1)
        self.assertEqual(result["exitCode"], 124)
        self.assertTrue(result["timedOut"])
        self.assertEqual(result["status"], "failed")

    def test_missing_executable_is_a_failure(self):
        result = collector.run_command(
            self.root, self.output, "missing", [str(self.root / "does-not-exist")],
            dict(os.environ), timeout_seconds=1,
        )
        self.assertEqual(result["exitCode"], 127)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["launchError"], "FileNotFoundError")

    def test_log_path_injection_is_rejected(self):
        for label in ("../escape", "/tmp/escape", "line\nbreak"):
            with self.subTest(label=label):
                with self.assertRaises(ValueError):
                    collector.run_command(self.root, self.output, label, [], {})

    def test_json_update_is_complete_and_has_no_temporary_tail(self):
        path = self.output / "receipt.json"
        collector.write_json(path, {"qualificationPassed": False})
        collector.write_json(path, {"qualificationPassed": False, "failure": "retained"})
        self.assertEqual(json.loads(path.read_text())["failure"], "retained")
        self.assertFalse(path.with_suffix(".json.tmp").exists())

    def test_failed_command_does_not_skip_later_commands(self):
        scripts = self.root / "scripts"
        scripts.mkdir()
        (scripts / SCRIPT.name).write_bytes(SCRIPT.read_bytes())
        self.output.mkdir()
        collector.write_json(self.output / "unittest.json", {
            "testsRun": 1, "skipped": [],
        })
        plan = [
            ("first-failure", [sys.executable, "-c", "raise SystemExit(3)"]),
            ("later-success", [sys.executable, "-c", "print('still executed')"]),
        ]
        def fixture_git(_root, *arguments, **_kwargs):
            return "" if arguments[0] == "status" else "a" * 40
        with patch.object(collector, "git", side_effect=fixture_git), patch.object(
            collector, "command_plan", return_value=plan,
        ):
            receipt = collector.qualify_lane(self.root, self.output, "a" * 40, "b" * 40, "fixture")
        self.assertEqual([row["exitCode"] for row in receipt["commandRecords"]], [3, 0])
        self.assertFalse(receipt["qualificationPassed"])
        self.assertFalse(receipt["independentAcceptance"])
        self.assertFalse(receipt["productionAccepted"])
        self.assertFalse(receipt["releaseAuthority"])
        self.assertIn("still executed", (self.output / "later-success.log").read_text())


if __name__ == "__main__":
    unittest.main()
