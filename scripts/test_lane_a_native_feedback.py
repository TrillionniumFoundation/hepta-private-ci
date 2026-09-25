"""Exercise native qualification failure propagation without running Cargo."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/run_lane_a_native_qualification.sh"
# Builtins avoid starting a Python interpreter for every mocked native command.
STUB = """#!/bin/sh
name="${0##*/}"
{ printf '%s\\t' "$name" "$@"; printf '\\n'; } >> "$LANE_A_TEST_LOG"
if [ "$name" = just ] && [ "$FAIL_TESTS" = 1 ]; then exit 17; fi
if [ "$name" = cargo ] && [ "$1" = clippy ] && [ "$FAIL_LINT" = 1 ]; then exit 23; fi
"""


class NativeFeedbackTests(unittest.TestCase):
    def run_profile(self, fail_tests=False, fail_lint=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("cargo", "just"):
                tool = root / name
                tool.write_text(STUB)
                tool.chmod(0o755)
            log = root / "commands.tsv"
            env = dict(
                os.environ,
                PATH=f"{root}:{os.environ['PATH']}",
                LANE_A_TEST_LOG=str(log),
                FAIL_TESTS=str(int(fail_tests)),
                FAIL_LINT=str(int(fail_lint)),
            )
            result = subprocess.run(
                ["bash", str(SCRIPT)],
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            commands = [
                line.rstrip("\t").split("\t") for line in log.read_text().splitlines()
            ]
        self.assertEqual(len(commands), 4, result.stderr)
        self.assertEqual(commands[0][0], "just")
        self.assertIn("test", commands[0])
        self.assertEqual(
            [row[:2] for row in commands[1:]],
            [["cargo", "clippy"], ["cargo", "check"], ["cargo", "clippy"]],
        )
        for command in commands:
            self.assertIn("--locked", command)
            self.assertNotIn("--retries", command)
        return result.returncode

    def test_all_success_is_success(self):
        self.assertEqual(self.run_profile(), 0)

    def test_test_failure_does_not_hide_lint_or_authority_binary_checks(self):
        self.assertEqual(self.run_profile(fail_tests=True), 17)

    def test_lint_failure_does_not_hide_later_checks(self):
        self.assertEqual(self.run_profile(fail_lint=True), 23)

    def test_first_failure_is_preserved(self):
        self.assertEqual(self.run_profile(fail_tests=True, fail_lint=True), 17)


if __name__ == "__main__":
    unittest.main()
