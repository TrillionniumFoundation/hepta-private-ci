"""Verify native/cross clippy selection without executing Bazel or a compiler."""

import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[2]
LABELS = [
    "//codex-rs/fake:fake-unit-tests-bin",
    "//codex-rs/fake:fake-integration-test-bin",
    "//codex-rs/fake:fake-integration-test-windows-cross-bin",
    "//codex-rs/fake:fake-other-manual",
]
PREFIX = ["//codex-rs/...", "-//codex-rs/v8-poc:all"]


class ClippyTargetSelectionTests(unittest.TestCase):
    def invoke(self, runner, args=(), labels=LABELS, query_exit=0):
        with TemporaryDirectory(prefix="clippy selection ") as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            (root / ".github/scripts").mkdir(parents=True)
            script = root / "scripts/list-bazel-clippy-targets.sh"
            shutil.copyfile(ROOT / "scripts/list-bazel-clippy-targets.sh", script)
            query = root / ".github/scripts/run-bazel-query-ci.sh"
            query.write_text(
                "#!/usr/bin/env bash\nset -eu\n"
                'printf "%s\\n" "$@" > query-argv.txt\n'
                'cat query-output.txt\nexit "${QUERY_EXIT}"\n',
                encoding="utf-8",
                newline="\n",
            )
            query.chmod(0o755)
            (root / "query-output.txt").write_text(
                "\n".join(labels) + ("\n" if labels else ""),
                encoding="utf-8",
                newline="\n",
            )
            env = dict(os.environ, RUNNER_OS=runner, QUERY_EXIT=str(query_exit))
            git_bash = (
                Path(os.environ.get("ProgramFiles", "C:/Program Files"))
                / "Git/bin/bash.exe"
            )
            bash = (
                str(git_bash)
                if os.name == "nt" and git_bash.is_file()
                else shutil.which("bash")
            )
            self.assertIsNotNone(bash, "Bash is required")
            result = subprocess.run(
                [bash, str(script), *args],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            argv_file = root / "query-argv.txt"
            queried = argv_file.read_text().splitlines() if argv_file.exists() else None
            return result, queried

    def test_native_platforms_preserve_native_helpers_not_cross_helpers(self):
        for runner in ("Windows", "Linux", "macOS", ""):
            with self.subTest(runner=runner):
                result, queried = self.invoke(runner)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    result.stdout.splitlines(),
                    PREFIX + [LABELS[0], LABELS[1], LABELS[3]],
                )
                self.assertEqual(
                    queried,
                    [
                        "--output=label",
                        "--",
                        'kind("rust_test rule", attr(tags, "manual", //codex-rs/... except //codex-rs/v8-poc/...))',
                    ],
                )

    def test_windows_cross_preserves_cross_and_unit_helpers(self):
        result, _ = self.invoke("Windows", ("--windows-cross-compile",))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(), PREFIX + [LABELS[0], LABELS[2], LABELS[3]]
        )

    def test_nonwindows_flag_preserves_existing_native_behavior(self):
        result, _ = self.invoke("Linux", ("--windows-cross-compile",))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(), PREFIX + [LABELS[0], LABELS[1], LABELS[3]]
        )

    def test_query_failure_never_publishes_partial_targets(self):
        for runner in ("Windows", "Linux"):
            result, _ = self.invoke(runner, query_exit=37)
            self.assertEqual(result.returncode, 37)
            self.assertEqual(result.stdout, "")

    def test_invalid_argument_does_not_query(self):
        result, queried = self.invoke("Windows", ("--unknown",))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIsNone(queried)

    def test_all_cross_helpers_do_not_remove_package_pattern(self):
        result, _ = self.invoke("Windows", labels=[LABELS[2]])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([line for line in result.stdout.splitlines() if line], PREFIX)

    def test_only_exact_cognitive_product_helper_is_nonwindows(self):
        target = "//codex-rs/hepta-agentd:hepta-agentd-cognitive-product-qualification-test-bin"
        lookalikes = [
            target + "-extra",
            target.replace("hepta-agentd:", "other:"),
            "//codex-rs/hepta-agentd:hepta-agentd-cognitive-write-qualification-test-bin",
        ]
        labels = [*LABELS, target, *lookalikes]
        for runner in ("Windows", "Linux", "macOS", ""):
            with self.subTest(runner=runner):
                result, _ = self.invoke(runner, labels=labels)
                self.assertEqual(result.returncode, 0, result.stderr)
                expected = PREFIX + [LABELS[0], LABELS[1], LABELS[3]]
                if runner != "Windows":
                    expected.append(target)
                self.assertEqual(result.stdout.splitlines(), expected + lookalikes)
        result, _ = self.invoke("Windows", labels=[target])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([line for line in result.stdout.splitlines() if line], PREFIX)

    def test_cognitive_filter_does_not_hide_failed_query(self):
        target = "//codex-rs/hepta-agentd:hepta-agentd-cognitive-product-qualification-test-bin"
        result, _ = self.invoke("Windows", labels=[target], query_exit=37)
        self.assertEqual(result.returncode, 37)
        self.assertEqual(result.stdout, "")

    def test_empty_query_preserves_package_pattern(self):
        result, _ = self.invoke("Windows", labels=[])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([line for line in result.stdout.splitlines() if line], PREFIX)


if __name__ == "__main__":
    unittest.main()
