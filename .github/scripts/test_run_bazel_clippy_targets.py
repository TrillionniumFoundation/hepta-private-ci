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
UNIX_PRODUCT = (
    "//codex-rs/hepta-agentd:hepta-agentd-cognitive-product-qualification-test-bin"
)
UNIX_READ_ONLY = "//codex-rs/hepta-agentd:hepta-agentd-read-only-product-test-bin"
UNIX_HELPER = "//codex-rs/fake:manual-unix-helper"
UNIX_TARGETS = [UNIX_PRODUCT, UNIX_READ_ONLY, UNIX_HELPER]
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
            "printf '%s\\n' called >> \"${DISCOVERY_QUERY_CALLS}\"\n"
            "if [[ ${DISCOVERY_QUERY_FAIL:-0} == 1 ]]; then\n"
            "  printf '%s\\n' '//codex-rs/partial:partial-unit-tests-bin'\n"
            "  exit 37\n"
            "fi\n"
            f"targets=('{UNIT}' '{NATIVE}' '{CROSS}' '{CUSTOM}')\n"
            "if [[ $* != *requires-unix* ]]; then\n"
            f"  targets+=('{UNIX_PRODUCT}' '{UNIX_READ_ONLY}' '{UNIX_HELPER}')\n"
            "fi\n"
            "if [[ ${DISCOVERY_QUERY_CRLF:-0} == 1 ]]; then\n"
            "  printf '%s\\r\\n' \"${targets[@]}\"\n"
            "else\n"
            "  printf '%s\\n' \"${targets[@]}\"\n"
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
        calls = self.root / "query-calls"
        calls.unlink(missing_ok=True)
        env = os.environ | {
            "RUNNER_OS": runner_os,
            "DISCOVERY_QUERY_CRLF": "1" if crlf else "0",
            "DISCOVERY_QUERY_FAIL": "1" if query_failure else "0",
            "DISCOVERY_QUERY_CALLS": str(calls),
        }
        result = subprocess.run(
            [self.bash, str(self.script), *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(
            calls.read_text().splitlines() if calls.exists() else [],
            [] if "--unknown" in args else ["called"],
        )
        return result

    def test_native_platforms_keep_native_and_unit_tests(self):
        for runner_os in ["Windows", "Linux", "macOS"]:
            for crlf in [False, True]:
                with self.subTest(runner_os=runner_os, crlf=crlf):
                    result = self.discover(runner_os, crlf=crlf)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    unix_targets = [] if runner_os == "Windows" else UNIX_TARGETS
                    self.assertEqual(
                        result.stdout.splitlines(),
                        PREFIX + [UNIT, NATIVE, CUSTOM] + unix_targets,
                    )

    def test_explicit_cross_keeps_cross_and_unit_tests(self):
        for runner_os in ["Windows", "Linux", "macOS"]:
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
