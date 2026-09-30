#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location(
    "hepta_nextest_require", Path(__file__).with_name("hepta-nextest-require.py")
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class RequiredNextestFilterTests(unittest.TestCase):
    def test_matching_lines_strips_ansi_and_deduplicates(self):
        output = (
            "\x1b[32mcrate::tests::required_case\x1b[0m\n"
            "crate::tests::required_case\n"
            "warning: required_case is mentioned only in a warning\n"
        )
        self.assertEqual(MODULE.matching_lines(output, "required_case"), ["crate::tests::required_case"])

    def test_zero_match_stops_before_execution_and_writes_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / "evidence.json"
            listed = subprocess.CompletedProcess(["cargo"], 0, "other::test\n", None)
            with mock.patch.object(MODULE, "run_capture", return_value=listed) as run:
                result = MODULE.main([
                    "--manifest-path", "Cargo.toml", "--package", "demo",
                    "--filter", "required_case", "--cwd", directory,
                    "--evidence", str(evidence),
                ])
            self.assertEqual(result, 4)
            self.assertEqual(run.call_count, 1)
            value = json.loads(evidence.read_text())
            self.assertEqual(value["list"]["matchCount"], 0)
            self.assertEqual(value["failure"], "required_filter_matched_zero_tests")
            self.assertFalse(value["claims"]["requiredTestExecuted"])

    def test_success_lists_then_runs_exact_filter(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / "evidence.json"
            results = [
                subprocess.CompletedProcess(["cargo"], 0, "demo::tests::required_case\n", None),
                subprocess.CompletedProcess(["cargo"], 0, "PASS required_case\n", None),
            ]
            with mock.patch.object(MODULE, "run_capture", side_effect=results) as run:
                result = MODULE.main([
                    "--manifest-path", "Cargo.toml", "--package", "demo",
                    "--filter", "required_case", "--cwd", directory,
                    "--evidence", str(evidence),
                ])
            self.assertEqual(result, 0)
            self.assertEqual(run.call_count, 2)
            value = json.loads(evidence.read_text())
            self.assertEqual(value["list"]["matchCount"], 1)
            self.assertTrue(value["claims"]["requiredTestDiscovered"])
            self.assertTrue(value["claims"]["requiredTestExecuted"])
            self.assertEqual(value["authority"], "DENY_ALL")

    def test_execution_failure_is_propagated(self):
        with tempfile.TemporaryDirectory() as directory:
            results = [
                subprocess.CompletedProcess(["cargo"], 0, "demo::required_case\n", None),
                subprocess.CompletedProcess(["cargo"], 17, "FAILED\n", None),
            ]
            with mock.patch.object(MODULE, "run_capture", side_effect=results):
                result = MODULE.main([
                    "--manifest-path", "Cargo.toml", "--package", "demo",
                    "--filter", "required_case", "--cwd", directory,
                ])
            self.assertEqual(result, 17)


if __name__ == "__main__":
    unittest.main()
