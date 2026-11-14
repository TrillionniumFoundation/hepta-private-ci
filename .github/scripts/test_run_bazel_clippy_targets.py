"""Exercise native and cross Clippy discovery through its real Bash entrypoint."""

from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[2] / "scripts/list-bazel-clippy-targets.sh"
UNIT = "//codex-rs/core:core-unit-tests-bin"
NATIVE = "//codex-rs/core:core-all-test-bin"
CROSS = "//codex-rs/core:core-all-test-windows-cross-bin"
CUSTOM = "//codex-rs/fake:manual-helper"
PREFIX = ["//codex-rs/...", "-//codex-rs/v8-poc:all"]


class ClippyTargetDiscoveryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="bazel clippy discovery ")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.script = self.root / "scripts/list-bazel-clippy-targets.sh"
        self.script.parent.mkdir()
        shutil.copyfile(SOURCE, self.script)
        query = self.root / ".github/scripts/run-bazel-query-ci.sh"
        query.parent.mkdir(parents=True)
        query.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "if [[ ${DISCOVERY_QUERY_FAIL:-0} == 1 ]]; then\n"
            "  printf '%s\\n' '//codex-rs/partial:partial-unit-tests-bin'\n"
            "  exit 37\n"
            "fi\n"
            "if [[ ${DISCOVERY_QUERY_CRLF:-0} == 1 ]]; then\n"
            f"  printf '%s\\r\\n' '{UNIT}' '{NATIVE}' '{CROSS}' '{CUSTOM}'\n"
            "else\n"
            f"  printf '%s\\n' '{UNIT}' '{NATIVE}' '{CROSS}' '{CUSTOM}'\n"
            "fi\n",
            encoding="utf-8",
            newline="\n",
        )
        query.chmod(0o755)
        self.bash = shutil.which("bash")
        if os.name == "nt":
            git_bash = (
                Path(os.environ.get("ProgramFiles", "C:/Program Files"))
                / "Git/bin/bash.exe"
            )
            if git_bash.is_file():
                self.bash = str(git_bash)
        self.assertIsNotNone(self.bash, "Bash is required to test target discovery")

    def discover(self, runner_os, *args, crlf=False, query_failure=False):
        env = os.environ | {
            "RUNNER_OS": runner_os,
            "DISCOVERY_QUERY_CRLF": "1" if crlf else "0",
            "DISCOVERY_QUERY_FAIL": "1" if query_failure else "0",
        }
        return subprocess.run(
            [self.bash, str(self.script), *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    def test_native_platforms_keep_native_and_unit_tests(self):
        for runner_os in ["Windows", "Linux", "macOS"]:
            for crlf in [False, True]:
                with self.subTest(runner_os=runner_os, crlf=crlf):
                    result = self.discover(runner_os, crlf=crlf)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(
                        result.stdout.splitlines(), PREFIX + [UNIT, NATIVE, CUSTOM]
                    )

    def test_explicit_cross_keeps_cross_and_unit_tests(self):
        for runner_os in ["Windows", "Linux"]:
            for crlf in [False, True]:
                with self.subTest(runner_os=runner_os, crlf=crlf):
                    result = self.discover(
                        runner_os, "--windows-cross-compile", crlf=crlf
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(
                        result.stdout.splitlines(), PREFIX + [UNIT, CROSS, CUSTOM]
                    )

    def test_failed_query_never_publishes_partial_targets(self):
        result = self.discover("Windows", query_failure=True)
        self.assertEqual(result.returncode, 37)
        self.assertEqual(result.stdout, "")

    def test_invalid_option_never_publishes_targets(self):
        result = self.discover("Windows", "--unknown")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("Usage:", result.stderr)


if __name__ == "__main__":
    unittest.main()
