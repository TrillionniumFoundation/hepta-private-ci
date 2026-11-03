#!/usr/bin/env python3
"""Regression for native Windows Clippy versus Windows-cross Bazel test helpers."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[2] / "scripts/list-bazel-clippy-targets.sh"
NATIVE = "//codex-rs/core:core-all-test-bin"
CROSS = "//codex-rs/core:core-all-test-windows-cross-bin"
UNIT = "//codex-rs/hepta-neuron:hepta-neuron-unit-tests-bin"
PREFIX = ["//codex-rs/...", "-//codex-rs/v8-poc:all"]


class ClippyTargetSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        script_dir = root / "scripts"
        script_dir.mkdir(parents=True)
        self.selector = script_dir / SOURCE.name
        shutil.copyfile(SOURCE, self.selector)

        query_dir = root / ".github/scripts"
        query_dir.mkdir(parents=True)
        query = query_dir / "run-bazel-query-ci.sh"
        query.write_text(
            "#!/bin/sh\n"
            'if [ "$CLIPPY_QUERY_FAIL" = "1" ]; then exit 29; fi\n'
            "printf '%s\\n' "
            f"'{UNIT}' '{NATIVE}' '{CROSS}'\n",
            encoding="utf-8",
        )
        query.chmod(0o755)
        self.bash = shutil.which("bash")
        self.assertIsNotNone(self.bash, "Bash is required for CI target selection")

    def select(self, runner_os, *args, fail=False):
        env = dict(os.environ)
        env["RUNNER_OS"] = runner_os
        env["CLIPPY_QUERY_FAIL"] = "1" if fail else "0"
        return subprocess.run(
            [self.bash, str(self.selector), *args],
            env=env, capture_output=True, text=True, timeout=15, check=False,
        )

    def test_linux_and_native_windows_preserve_native_test_helpers(self):
        for runner in ("Linux", "Windows", "macOS"):
            with self.subTest(runner=runner):
                result = self.select(runner)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.splitlines(), PREFIX + [UNIT, NATIVE])

    def test_explicit_windows_cross_leg_preserves_cross_helpers(self):
        result = self.select("Windows", "--windows-cross-compile")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), PREFIX + [UNIT, CROSS])

    def test_failed_query_emits_no_partial_target_list(self):
        result = self.select("Windows", fail=True)
        self.assertEqual(result.returncode, 29, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_unknown_selector_option_is_rejected(self):
        result = self.select("Windows", "--invalid-selector")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Usage:", result.stderr)


if __name__ == "__main__":
    unittest.main()
