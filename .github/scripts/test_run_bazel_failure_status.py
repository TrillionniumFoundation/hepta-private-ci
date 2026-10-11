#!/usr/bin/env python3
"""Exercise real shell failures without replacing Bazel or its original controls."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

import test_run_bazel_ci as original


class BazelFailureStatusTests(unittest.TestCase):
    # Share the original recording child and Windows configuration, not the
    # original test inventory. Every original test continues to run once.
    setUp = original.RunBazelCiIntegrationTest.setUp
    run_wrapper = original.RunBazelCiIntegrationTest.run_wrapper

    def prepend_tool_path(self, name: str) -> Path:
        """Use a space-free directory so Git Bash can resolve fake tools on Windows."""
        tools = Path(tempfile.mkdtemp(prefix=f"bazel-{name}-"))
        self.addCleanup(shutil.rmtree, tools)
        self.env["PATH"] = str(tools) + os.pathsep + self.env.get("PATH", "")
        return tools

    def test_failed_capture_cannot_report_success(self) -> None:
        tools = self.prepend_tool_path("capture")
        tee = tools / "tee"
        tee.write_text("#!/bin/sh\ncat >/dev/null\nexit 23\n", encoding="utf-8")
        tee.chmod(0o755)
        result, calls = self.run_wrapper("--", "test", "--", "//fake:target")
        self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
        self.assertEqual(len(calls), 1)

    def test_failed_capture_preserves_primary_bazel_failure(self) -> None:
        tools = self.prepend_tool_path("capture")
        tee = tools / "tee"
        tee.write_text("#!/bin/sh\ncat >/dev/null\nexit 23\n", encoding="utf-8")
        tee.chmod(0o755)
        self.env["BAZEL_PROBE_FAIL"] = "1"
        result, calls = self.run_wrapper("--", "test", "--", "//fake:target")
        self.assertEqual(result.returncode, 37, result.stdout + result.stderr)
        self.assertEqual(len(calls), 1)

    def test_failed_test_log_tail_preserves_primary_bazel_failure(self) -> None:
        tools = self.prepend_tool_path("diagnostic")
        tail = tools / "tail"
        tail.write_text("#!/bin/sh\nexit 29\n", encoding="utf-8")
        tail.chmod(0o755)
        self.env["BAZEL_PROBE_FAIL"] = "1"
        result, calls = self.run_wrapper(
            "--print-failed-test-logs", "--", "test", "--", "//fake:target"
        )
        self.assertEqual(result.returncode, 37, result.stdout + result.stderr)
        self.assertIn("Bazel test diagnostics failed", result.stderr)
        self.assertEqual(len(calls), 2)

    def test_original_success_and_complete_failure_controls_remain(self) -> None:
        result, _ = self.run_wrapper("--", "test", "--", "//fake:target")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.env["BAZEL_PROBE_FAIL"] = "1"
        result, calls = self.run_wrapper(
            "--print-failed-action-summary",
            "--print-failed-test-logs",
            "--",
            "test",
            "--",
            "//fake:target",
        )
        self.assertEqual(result.returncode, 37, result.stdout + result.stderr)
        self.assertIn("undefined symbol: __stack_chk_fail", result.stdout)
        self.assertIn("actual failing test diagnostic", result.stdout)
        self.assertEqual(len(calls), 3)


if __name__ == "__main__":
    unittest.main()
