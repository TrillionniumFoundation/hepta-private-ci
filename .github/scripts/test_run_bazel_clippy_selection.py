"""Execute the real Clippy workflow shell with recording query/build commands."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[2]
UNIX_HELPER = (
    "//codex-rs/hepta-agentd:hepta-agentd-cognitive-product-qualification-test-bin"
)


class ClippySelectionTest(unittest.TestCase):
    def run_step(self, runner, targets, exit_code=0, query_exit_code=0):
        workflow = (ROOT / ".github/workflows/bazel.yml").read_text(encoding="utf-8")
        section = workflow.split(
            "      - name: bazel build --config=clippy lint targets\n", 1
        )[1]
        shell = textwrap.dedent(
            section.split("        run: |\n", 1)[1].split("\n      - name:", 1)[0]
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            (root / ".github/scripts").mkdir(parents=True)
            (root / "bazel-execution-logs").mkdir()
            (root / "roster").write_text(
                "\n".join(targets) + "\n", encoding="utf-8", newline="\n"
            )
            commands = {
                "scripts/list-bazel-clippy-targets.sh": (
                    'cat roster\nexit "$PROBE_QUERY_EXIT_CODE"\n'
                ),
                ".github/scripts/run-bazel-ci.sh": (
                    'printf "%s\\0" "$@" > invocation\nexit "$PROBE_EXIT_CODE"\n'
                ),
            }
            for path, command in commands.items():
                script = root / path
                script.write_text(
                    "#!/usr/bin/env bash\n" + command, encoding="utf-8", newline="\n"
                )
                script.chmod(0o755)
            bash = shutil.which("bash")
            self.assertIsNotNone(bash)
            (root / "workflow.sh").write_text(shell, encoding="utf-8", newline="\n")
            result = subprocess.run(
                [bash, "-e", "-o", "pipefail", "workflow.sh"],
                cwd=root,
                env={
                    **os.environ,
                    "RUNNER_OS": runner,
                    "RUNNER_TEMP": root.as_posix(),
                    "GITHUB_SHA": "a" * 40,
                    "PROBE_EXIT_CODE": str(exit_code),
                    "PROBE_QUERY_EXIT_CODE": str(query_exit_code),
                },
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=False,
                timeout=30,
            )
            if query_exit_code:
                self.assertFalse((root / "invocation").exists())
                return result, [], []
            invocation = (root / "invocation").read_bytes().decode().split("\0")[:-1]
            requested = (
                (root / "bazel-execution-logs/clippy-requested-targets.nul")
                .read_bytes()
                .decode()
                .split("\0")[:-1]
            )
        return result, invocation, requested

    def test_native_windows_keeps_all_compatible_helpers_and_full_evidence(self):
        targets = [
            "//codex-rs/...",
            "-//codex-rs/v8-poc:all",
            "//codex-rs/core:core-all-test-windows-cross-bin",
            "//codex-rs/core:core-all-test-bin",
            UNIX_HELPER,
            "//codex-rs/hepta-agentd:hepta-agentd-cognitive-write-qualification-test-bin",
            "//codex-rs/future:unknown-native-incompatible-test-bin",
            "//codex-rs/future:windows-cross-bin-extra",
            "//codex-rs/future:label with spaces-测试",
            "//codex-rs/core:core-unit-tests-bin",
        ]
        result, invocation, requested = self.run_step("Windows", targets)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(requested, targets)
        self.assertEqual(
            invocation[invocation.index("--", 3) + 1 :],
            targets[:2] + targets[3:4] + targets[5:],
        )
        self.assertIn("--windows-msvc-host-platform", invocation)
        self.assertIn("--platforms=//:windows_x86_64_msvc", invocation)
        self.assertIn("--config=clippy", invocation)
        self.assertNotIn("--skip_incompatible_explicit_targets", invocation)
        self.assertEqual(
            result.stdout.count("Native MSVC excludes incompatible helper:"), 2
        )

    def test_query_failure_stops_before_build(self):
        result, _, _ = self.run_step("Windows", ["//partial:target"], query_exit_code=9)
        self.assertEqual(result.returncode, 9)

    def test_other_platforms_preserve_their_complete_query_roster(self):
        targets = ["//codex-rs/...", UNIX_HELPER, "//codex-rs/core:core-all-test-bin"]
        for runner in ("Linux", "macOS"):
            with self.subTest(runner=runner):
                result, invocation, requested = self.run_step(runner, targets)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(requested, targets)
                self.assertEqual(invocation[invocation.index("--", 2) + 1 :], targets)
                self.assertNotIn("--windows-msvc-host-platform", invocation)
                self.assertNotIn("Native MSVC excludes", result.stdout)

    def test_compatible_lint_or_unexpected_incompatibility_failure_is_not_masked(self):
        targets = ["//codex-rs/...", "//codex-rs/future:new-native-test-bin"]
        for code in (1, 37):
            with self.subTest(code=code):
                result, invocation, requested = self.run_step("Windows", targets, code)
                self.assertEqual(result.returncode, code)
                self.assertEqual(requested, targets)
                self.assertIn(targets[-1], invocation)
                self.assertNotIn("--skip_incompatible_explicit_targets", invocation)


if __name__ == "__main__":
    unittest.main()
