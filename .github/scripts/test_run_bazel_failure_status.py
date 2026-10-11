#!/usr/bin/env python3
"""Exercise real shell failures without replacing Bazel or its original controls."""

import json
import subprocess
import unittest

import test_run_bazel_ci as original


class BazelFailureStatusTests(unittest.TestCase):
    # Share the original recording child and Windows configuration, not the
    # original test inventory. Every original test continues to run once.
    setUp = original.RunBazelCiIntegrationTest.setUp

    def run_wrapper(self, *args: str):
        # Git Bash prepends its own tools while starting on Windows. Install
        # fault tools after startup so the real shell actually executes them.
        script = r"""fault_tools=$1
shift
if command -v cygpath >/dev/null 2>&1; then
    fault_tools=$(cygpath -u "$fault_tools") || exit
fi
export PATH="$fault_tools:$PATH"
source "$@"
"""
        result = subprocess.run(
            [
                self.bash,
                "-c",
                script,
                "fault-tools",
                str(self.root / "fault tools"),
                str(original.SCRIPTS / "run-bazel-ci.sh"),
                *args,
            ],
            env=self.env,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertTrue(self.log.exists(), result.stdout + result.stderr)
        calls = [
            json.loads(line)
            for line in self.log.read_text(encoding="utf-8").splitlines()
        ]
        return result, calls

    def test_failed_capture_cannot_report_success(self) -> None:
        tools = self.root / "fault tools"
        tools.mkdir()
        tee = tools / "tee"
        tee.write_text(
            "#!/bin/sh\necho capture-fault-executed >&2\ncat >/dev/null\nexit 23\n",
            encoding="utf-8",
            newline="\n",
        )
        tee.chmod(0o755)
        result, calls = self.run_wrapper("--", "test", "--", "//fake:target")
        self.assertIn("capture-fault-executed", result.stderr)
        self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
        self.assertEqual(len(calls), 1)

    def test_failed_capture_preserves_primary_bazel_failure(self) -> None:
        tools = self.root / "fault tools"
        tools.mkdir()
        tee = tools / "tee"
        tee.write_text(
            "#!/bin/sh\necho capture-fault-executed >&2\ncat >/dev/null\nexit 23\n",
            encoding="utf-8",
            newline="\n",
        )
        tee.chmod(0o755)
        self.env["BAZEL_PROBE_FAIL"] = "1"
        result, calls = self.run_wrapper("--", "test", "--", "//fake:target")
        self.assertEqual(result.returncode, 37, result.stdout + result.stderr)
        self.assertIn("capture-fault-executed", result.stderr)
        self.assertEqual(len(calls), 1)

    def test_failed_test_log_tail_preserves_primary_bazel_failure(self) -> None:
        tools = self.root / "fault tools"
        tools.mkdir()
        tail = tools / "tail"
        tail.write_text(
            "#!/bin/sh\necho tail-fault-executed >&2\nexit 29\n",
            encoding="utf-8",
            newline="\n",
        )
        tail.chmod(0o755)
        self.env["BAZEL_PROBE_FAIL"] = "1"
        result, calls = self.run_wrapper(
            "--print-failed-test-logs", "--", "test", "--", "//fake:target"
        )
        self.assertEqual(result.returncode, 37, result.stdout + result.stderr)
        self.assertIn("tail-fault-executed", result.stderr)
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
