"""Collector integrity tests using real Git and subprocesses, not runtime acceptance."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/control_engineering_candidate_evidence.py"
SPEC = importlib.util.spec_from_file_location("ce_integrity_collector_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)


class CandidateEvidenceIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "repository"
        self.root.mkdir()
        self.output = self.root.parent / "evidence"
        (self.root / "scripts").mkdir()
        (self.root / "scripts" / SCRIPT.name).write_bytes(SCRIPT.read_bytes())
        (self.root / "tracked.txt").write_text("original\n", encoding="utf-8")
        self.git("init", "-q")
        self.git("config", "user.name", "Collector fixture")
        self.git("config", "user.email", "fixture@invalid.example")
        self.git("config", "commit.gpgsign", "false")
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")
        self.source = self.git("rev-parse", "HEAD")
        self.output.mkdir()
        self.report = {
            "testsRun": 1, "successful": True, "failures": [], "errors": [],
            "skipped": [], "expectedFailures": [], "unexpectedSuccesses": [],
        }
        collector.write_json(self.output / "unittest.json", self.report)

    def git(self, *arguments: str) -> str:
        return subprocess.check_output(
            ["git", *arguments], cwd=self.root, text=True,
            stderr=subprocess.PIPE, timeout=10,
        ).strip()

    def run_lane(self, plan: list[tuple[str, list[str]]] | None = None) -> dict:
        if plan is None:
            plan = [("probe", [sys.executable, "-c", "print('collector fixture')"])]
        with patch.object(collector, "command_plan", return_value=plan):
            result = collector.qualify_lane(
                self.root, self.output, self.source, self.source, "source-head"
            )
        stored = json.loads((self.output / "receipt.json").read_text())
        self.assertEqual(stored["qualificationPassed"], result["qualificationPassed"])
        for flag in ("independentAcceptance", "productionAccepted", "releaseAuthority"):
            self.assertFalse(result[flag])
        return result

    def test_clean_identity_and_consistent_report_pass_collector_only(self) -> None:
        result = self.run_lane()
        self.assertTrue(result["qualificationPassed"])
        self.assertTrue(result["commandLogsIntact"])
        self.assertTrue(result["sourceIdentityPreserved"])

    def test_new_commit_with_clean_worktree_is_not_the_tested_source(self) -> None:
        result = self.run_lane([("commit-drift", [sys.executable, "-c",
            "from pathlib import Path; import subprocess; "
            "Path('tracked.txt').write_text('changed'); "
            "subprocess.run(['git','commit','-qam','changed'],check=True)"])])
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertNotEqual(self.git("rev-parse", "HEAD"), self.source)
        self.assertFalse(result["qualificationPassed"])
        self.assertFalse(result["sourceIdentityPreserved"])

    def test_same_tree_new_empty_commit_also_rejects(self) -> None:
        result = self.run_lane([("empty-commit", ["git", "commit", "--allow-empty", "-qm", "drift"])])
        self.assertEqual(result["testedTree"], self.git("rev-parse", "HEAD^{tree}"))
        self.assertFalse(result["qualificationPassed"])

    def test_restoring_head_does_not_erase_earlier_identity_drift(self) -> None:
        result = self.run_lane([
            ("empty-commit", ["git", "commit", "--allow-empty", "-qm", "drift"]),
            ("restore-head", ["git", "reset", "--hard", self.source]),
        ])
        self.assertEqual(self.git("rev-parse", "HEAD"), self.source)
        self.assertFalse(result["sourceIdentityPreserved"])
        self.assertFalse(result["qualificationPassed"])

    def test_failed_report_cannot_pass_with_zero_command_exit(self) -> None:
        self.report.update(successful=False, failures=["fixture.failure"])
        collector.write_json(self.output / "unittest.json", self.report)
        result = self.run_lane()
        self.assertTrue(result["allChecksPassed"])
        self.assertFalse(result["qualificationPassed"])
        self.assertFalse(result["testsSuccessful"])

    def test_contradictory_success_with_errors_is_rejected(self) -> None:
        self.report["errors"] = ["fixture.error"]
        collector.write_json(self.output / "unittest.json", self.report)
        self.assertFalse(self.run_lane()["qualificationPassed"])

    def test_malformed_report_retains_diagnostic_instead_of_crashing(self) -> None:
        (self.output / "unittest.json").write_text("{broken", encoding="utf-8")
        result = self.run_lane()
        self.assertFalse(result["qualificationPassed"])
        self.assertIsNotNone(result["unittestReportError"])
        self.assertIn("unittest.json", result["artifacts"])

    def test_absent_report_fails_closed(self) -> None:
        (self.output / "unittest.json").unlink()
        self.assertFalse(self.run_lane()["qualificationPassed"])

    def test_boolean_count_and_nonboolean_success_are_invalid(self) -> None:
        for update in ({"testsRun": True}, {"successful": "true"}, {"skipped": None}):
            with self.subTest(update=update):
                collector.write_json(self.output / "unittest.json", {**self.report, **update})
                result = self.run_lane()
                self.assertFalse(result["qualificationPassed"])
                self.assertEqual(result["unittestReportError"], "unittest_report_invalid_shape")

    def test_oversized_report_is_rejected(self) -> None:
        with (self.output / "unittest.json").open("wb") as stream:
            stream.truncate(8 * 1024 * 1024 + 1)
        result = self.run_lane()
        self.assertEqual(result["unittestReportError"], "unittest_report_budget_exceeded")
        self.assertFalse(result["qualificationPassed"])

    def test_later_log_replacement_invalidates_evidence(self) -> None:
        code = f"from pathlib import Path; Path({str(self.output / 'first.log')!r}).write_text('changed')"
        result = self.run_lane([
            ("first", [sys.executable, "-c", "print('original')"]),
            ("replace-log", [sys.executable, "-c", code]),
        ])
        self.assertTrue(result["allChecksPassed"])
        self.assertFalse(result["commandLogsIntact"])
        self.assertFalse(result["qualificationPassed"])

    def test_later_log_deletion_retains_failed_receipt(self) -> None:
        code = f"from pathlib import Path; Path({str(self.output / 'first.log')!r}).unlink()"
        result = self.run_lane([
            ("first", [sys.executable, "-c", "print('original')"]),
            ("delete-log", [sys.executable, "-c", code]),
        ])
        self.assertFalse(result["commandLogsIntact"])
        self.assertFalse(result["qualificationPassed"])

    def test_untracked_source_drift_rejects(self) -> None:
        result = self.run_lane([("untracked", [sys.executable, "-c",
            "from pathlib import Path; Path('untracked.py').write_text('x=1')"])])
        self.assertFalse(result["qualificationPassed"])
        self.assertIn("untracked.py", result["checkoutStatusAfter"])

    def test_skips_and_expected_failures_are_not_full_qualification(self) -> None:
        for field in ("skipped", "expectedFailures", "unexpectedSuccesses"):
            with self.subTest(field=field):
                collector.write_json(self.output / "unittest.json", {**self.report, field: ["fixture"]})
                self.assertFalse(self.run_lane()["qualificationPassed"])

    def test_empty_plan_cannot_qualify(self) -> None:
        self.assertFalse(self.run_lane([])["qualificationPassed"])


if __name__ == "__main__":
    unittest.main()
