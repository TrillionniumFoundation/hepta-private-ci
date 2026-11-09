"""Reject native admission after failed or source-changing strict preparation."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import windows_fixture_followup as subject


class StrictAdmissionTests(unittest.TestCase):
    def test_failed_just_fix_does_not_run_readonly_lint_or_admit_native(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            with (
                patch.object(subject, "capture", return_value={"exitCode": 1}) as run,
                patch.object(subject, "check_sources"),
                self.assertRaisesRegex(ValueError, "native case remains not_run"),
            ):
                subject.strict_owner(
                    {"package": "codex-example"}, output, output, output, {}
                )
            self.assertEqual(run.call_count, 1)
            result = json.loads((output / "strict-preparation.json").read_text())
            self.assertFalse(result["passed"])
            self.assertEqual(result["steps"], [{"exitCode": 1}])

    def test_successful_fix_with_source_drift_does_not_continue(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            with (
                patch.object(subject, "capture", return_value={"exitCode": 0}) as run,
                patch.object(
                    subject, "check_sources", side_effect=ValueError("source drift")
                ),
                self.assertRaisesRegex(ValueError, "source drift"),
            ):
                subject.strict_owner(
                    {"package": "codex-example"}, output, output, output, {}
                )
            self.assertEqual(run.call_count, 1)
            result = json.loads((output / "strict-preparation.json").read_text())
            self.assertFalse(result["passed"])

    def test_failed_nonmutating_lint_cannot_be_rescued_by_successful_fix(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            with (
                patch.object(
                    subject, "capture", side_effect=[{"exitCode": 0}, {"exitCode": 1}]
                ) as run,
                patch.object(subject, "check_sources"),
                self.assertRaisesRegex(ValueError, "native case remains not_run"),
            ):
                subject.strict_owner(
                    {"package": "codex-example"}, output, output, output, {}
                )
            self.assertEqual(run.call_count, 2)
            self.assertEqual(run.call_args_list[0].args[2][:2], ["just", "fix"])
            self.assertEqual(run.call_args_list[1].args[2][:2], ["cargo", "clippy"])
            result = json.loads((output / "strict-preparation.json").read_text())
            self.assertFalse(result["passed"])


if __name__ == "__main__":
    unittest.main()
