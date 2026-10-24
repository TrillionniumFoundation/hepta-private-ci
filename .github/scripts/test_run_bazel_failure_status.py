#!/usr/bin/env python3
"""Exercise real shell failures without replacing Bazel or its original controls."""

import subprocess
import unittest

import test_run_bazel_ci as original


class BazelFailureStatusTests(unittest.TestCase):
    # Share the original recording child and Windows configuration, not the
    # original test inventory. Every original test continues to run once.
    setUp = original.RunBazelCiIntegrationTest.setUp
    run_wrapper = original.RunBazelCiIntegrationTest.run_wrapper

    def install_failure_tool(self, name: str, body: str) -> None:
        tools = self.root / "failure tools"
        tools.mkdir(exist_ok=True)
        tool = tools / name
        # Git Bash can prepend its own tools when importing a native Windows
        # PATH. Set this test's override after shell startup instead. LF-only
        # executable scripts also avoid a Windows text-mode shebang rewrite.
        tool.write_bytes(
            (f"#!/bin/sh\nprintf 'bazel-fault-tool:{name}\\n' >&2\n" + body).encode()
        )
        tool.chmod(0o755)
        startup = self.root / "failure environment.sh"
        startup.write_bytes(
            b'failure_tools="$BAZEL_FAILURE_TOOLS"\n'
            b'if command -v cygpath >/dev/null 2>&1; then\n'
            b'  failure_tools="$(cygpath -u "$failure_tools")" || exit\n'
            b'fi\n'
            b'export PATH="$failure_tools:$PATH"\n'
            b'hash -r\n'
        )
        # This fixture is private to the test's temporary directory/environment;
        # neither the product wrapper nor Bazel's action environment is changed.
        self.env["BAZEL_FAILURE_TOOLS"] = tools.as_posix()
        self.env["BASH_ENV"] = startup.as_posix()

    def test_failed_capture_cannot_report_success(self) -> None:
        self.install_failure_tool("tee", "cat >/dev/null\nexit 23\n")
        result, calls = self.run_wrapper("--", "test", "--", "//fake:target")
        self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result.stderr.count("bazel-fault-tool:tee"), 1)

    def test_failed_capture_preserves_primary_bazel_failure(self) -> None:
        self.install_failure_tool("tee", "cat >/dev/null\nexit 23\n")
        self.env["BAZEL_PROBE_FAIL"] = "1"
        result, calls = self.run_wrapper("--", "test", "--", "//fake:target")
        self.assertEqual(result.returncode, 37, result.stdout + result.stderr)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result.stderr.count("bazel-fault-tool:tee"), 1)

    def test_failed_test_log_tail_preserves_primary_bazel_failure(self) -> None:
        self.install_failure_tool("tail", "exit 29\n")
        self.env["BAZEL_PROBE_FAIL"] = "1"
        result, calls = self.run_wrapper(
            "--print-failed-test-logs", "--", "test", "--", "//fake:target"
        )
        self.assertEqual(result.returncode, 37, result.stdout + result.stderr)
        self.assertIn("Bazel test diagnostics failed", result.stderr)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result.stderr.count("bazel-fault-tool:tail"), 1)

    def test_original_success_and_complete_failure_controls_remain(self) -> None:
        result, _ = self.run_wrapper("--", "test", "--", "//fake:target")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.env["BAZEL_PROBE_FAIL"] = "1"
        result, calls = self.run_wrapper(
            "--print-failed-action-summary", "--print-failed-test-logs",
            "--", "test", "--", "//fake:target"
        )
        self.assertEqual(result.returncode, 37, result.stdout + result.stderr)
        self.assertIn("undefined symbol: __stack_chk_fail", result.stdout)
        self.assertIn("actual failing test diagnostic", result.stdout)
        self.assertEqual(len(calls), 3)

    def test_failure_tool_runs_after_noninteractive_shell_startup(self) -> None:
        self.install_failure_tool("tee", "cat >/dev/null\nexit 23\n")
        result = subprocess.run(
            [self.bash, "--noprofile", "--norc", "-c", "tee </dev/null"],
            env=self.env,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
        self.assertEqual(result.stderr.count("bazel-fault-tool:tee"), 1)
        self.assertFalse(self.log.exists(), "the tool probe must not invoke Bazel")

    def test_failed_capture_on_build_cannot_report_success(self) -> None:
        self.install_failure_tool("tee", "cat >/dev/null\nexit 23\n")
        result, calls = self.run_wrapper("--", "build", "--", "//fake:target")
        self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result.stderr.count("bazel-fault-tool:tee"), 1)


if __name__ == "__main__":
    unittest.main()
