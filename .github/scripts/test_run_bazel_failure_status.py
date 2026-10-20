#!/usr/bin/env python3
"""Exercise real shell failures without replacing Bazel or its original controls."""

import unittest

import test_run_bazel_ci as original


class BazelFailureStatusTests(unittest.TestCase):
    # Share the original recording child and Windows configuration, not the
    # original test inventory. Every original test continues to run once.
    setUp = original.RunBazelCiIntegrationTest.setUp
    run_wrapper = original.RunBazelCiIntegrationTest.run_wrapper

    def fail_shell_command(self, command: str, status: int) -> None:
        # Git Bash reconstructs PATH on Windows and can put /usr/bin before a
        # Python-supplied shim directory. Install the fault in the same shell
        # that runs the actual pipeline, after that startup processing.
        startup = self.root / "failure injector.sh"
        drain = "cat >/dev/null; " if command == "tee" else ""
        startup.write_text(
            f"{command}() {{ {drain}printf 'injected {command} failure\\n' >&2; return {status}; }}\n",
            encoding="utf-8",
            newline="\n",
        )
        self.env["BASH_ENV"] = startup.as_posix()

    def test_failed_capture_cannot_report_success(self) -> None:
        self.fail_shell_command("tee", 23)
        result, calls = self.run_wrapper("--", "test", "--", "//fake:target")
        self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
        self.assertIn("injected tee failure", result.stderr)
        self.assertEqual(len(calls), 1)

    def test_failed_capture_preserves_primary_bazel_failure(self) -> None:
        self.fail_shell_command("tee", 23)
        self.env["BAZEL_PROBE_FAIL"] = "1"
        result, calls = self.run_wrapper("--", "test", "--", "//fake:target")
        self.assertEqual(result.returncode, 37, result.stdout + result.stderr)
        self.assertIn("injected tee failure", result.stderr)
        self.assertEqual(len(calls), 1)

    def test_failed_test_log_tail_preserves_primary_bazel_failure(self) -> None:
        self.fail_shell_command("tail", 29)
        self.env["BAZEL_PROBE_FAIL"] = "1"
        result, calls = self.run_wrapper(
            "--print-failed-test-logs", "--", "test", "--", "//fake:target"
        )
        self.assertEqual(result.returncode, 37, result.stdout + result.stderr)
        self.assertIn("injected tail failure", result.stderr)
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
