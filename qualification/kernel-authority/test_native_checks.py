"""Quality-harness regressions; these mocks are not native execution receipts."""
import copy
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

SPEC = importlib.util.spec_from_file_location("authority_native_checks", Path(__file__).with_name("run_native_checks.py"))
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class NativeHarnessTests(unittest.TestCase):
    def rows(self):
        return [{"name": n, "workingDirectory": c, "command": command, "passed": True,
                 "exitCode": 0, "executionError": None} for n, c, command in MODULE.command_plan()]

    def test_complete_plan_is_required(self):
        plan, rows = MODULE.command_plan(), self.rows()
        self.assertTrue(MODULE.complete_pass(plan, rows, True))
        self.assertFalse(MODULE.complete_pass(plan, rows[:-1], True))
        self.assertFalse(MODULE.complete_pass(plan, rows, False))
        self.assertFalse(MODULE.complete_pass(plan, rows, 1))

    def test_failure_reordering_or_substitution_cannot_pass(self):
        plan, original = MODULE.command_plan(), self.rows()
        for key, value in (("passed", False), ("exitCode", True), ("exitCode", 1),
                           ("command", ["true"]), ("executionError", "timeout")):
            rows = copy.deepcopy(original)
            rows[0][key] = value
            self.assertFalse(MODULE.complete_pass(plan, rows, True))
        self.assertFalse(MODULE.complete_pass(plan, list(reversed(original)), True))

    def test_native_tests_fail_on_empty_selection_and_disable_retries(self):
        commands = {name: cmd for name, _, cmd in MODULE.command_plan()}
        tests = commands["native-package-tests"]
        self.assertIn("--no-tests=fail", tests)
        self.assertEqual(tests[tests.index("--retries") + 1], "0")
        self.assertEqual(commands["strict-clippy"][-3:], ["--", "-D", "warnings"])
        for package in MODULE.PACKAGES:
            self.assertIn(package, tests)
            self.assertIn(package, commands["all-target-check"])

    def test_workflow_never_uses_repair_or_all_features(self):
        for _, _, command in MODULE.command_plan():
            self.assertNotIn("--fix", command)
            self.assertNotIn("--all-features", command)
        status = next(command for name, _, command in MODULE.command_plan() if name == "status-projections")
        self.assertEqual(status[-1], "check")

    def test_timeout_and_missing_command_produce_retained_failure(self):
        for failure, exit_code in ((subprocess.TimeoutExpired(["missing"], 1), 124),
                                    (FileNotFoundError("missing"), 127)):
            with tempfile.TemporaryDirectory() as directory, patch.object(MODULE.subprocess, "run", side_effect=failure):
                result = MODULE.run_step("fixture", ".", ["missing"], Path(directory), 1)
                self.assertEqual(result["exitCode"], exit_code)
                self.assertFalse(result["passed"])
                self.assertGreater(result["logBytes"], 0)
                self.assertEqual(len(result["logSha256"]), 64)

    def test_success_records_actual_command_and_output(self):
        def fake(command, **kwargs):
            kwargs["stdout"].write(b"actual fixture output\n")
            return SimpleNamespace(returncode=0)
        with tempfile.TemporaryDirectory() as directory, patch.object(MODULE.subprocess, "run", side_effect=fake):
            result = MODULE.run_step("fixture", ".", ["fixture-tool", "arg"], Path(directory), 1)
            self.assertTrue(result["passed"])
            self.assertEqual(result["command"], ["fixture-tool", "arg"])
            self.assertEqual((Path(directory) / result["logPath"]).read_bytes(), b"actual fixture output\n")


if __name__ == "__main__":
    unittest.main()
