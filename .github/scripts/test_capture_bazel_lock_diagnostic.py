"""Exercise failure diagnostics without executing Bazel or changing qualification."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github/scripts/capture-bazel-lock-diagnostic.sh"


@unittest.skipUnless(sys.platform == "linux", "diagnostic runs only on Linux")
class LockDiagnosticTests(unittest.TestCase):
    def run_fixture(self, generator_status, mutate_input=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "codex-rs").mkdir()
            (root / "bin").mkdir()
            for path in (
                "MODULE.bazel",
                "codex-rs/Cargo.lock",
                "codex-rs/Cargo.toml",
                ".bazelversion",
            ):
                (root / path).write_text("fixed input\n")
            (root / "MODULE.bazel.lock").write_text("original lock\n")
            subprocess.run(["git", "init", "-q", directory], check=True)
            subprocess.run(["git", "-C", directory, "add", "."], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    directory,
                    "-c",
                    "user.name=Fixture",
                    "-c",
                    "user.email=fixture@example.invalid",
                    "commit",
                    "-qm",
                    "fixture",
                ],
                check=True,
            )
            fake_just = root / "bin/just"
            fake_just.write_text(
                '#!/bin/sh\n[ "$*" = "bazel-lock-update" ] || exit 99\n'
                'printf "generated lock\\n" > MODULE.bazel.lock\n'
                + (
                    'printf "changed input\\n" > codex-rs/Cargo.lock\n'
                    if mutate_input
                    else ""
                )
                + f"exit {generator_status}\n"
            )
            fake_just.chmod(0o755)
            output = root / "diagnostic"
            result = subprocess.run(
                ["bash", str(SCRIPT), str(output)],
                cwd=root,
                env={
                    **os.environ,
                    "PATH": str(root / "bin") + os.pathsep + os.environ["PATH"],
                },
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                (root / "MODULE.bazel.lock").read_text(), "original lock\n"
            )
            self.assertEqual(
                (output / "MODULE.bazel.lock.generated").read_text(), "generated lock\n"
            )
            self.assertEqual(
                (output / "generation-exit-code.txt").read_text(),
                f"{generator_status}\n",
            )
            self.assertIn(
                "+generated lock", (output / "MODULE.bazel.lock.diff").read_text()
            )
            self.assertNotIn("generation.log", {path.name for path in output.iterdir()})
            return result.returncode

    def test_success_and_failure_restore_original_and_preserve_generator_status(self):
        for status in (0, 17):
            with self.subTest(status=status):
                self.assertEqual(self.run_fixture(status), status)

    def test_dependency_input_mutation_fails_closed(self):
        self.assertNotEqual(self.run_fixture(0, mutate_input=True), 0)

    def test_diagnostics_are_guarded_by_failed_strict_linux_check(self):
        workflow = (ROOT / ".github/workflows/bazel.yml").read_text()
        capture = workflow.split(
            "      - name: Capture failed lock regeneration diagnostic\n", 1
        )[1]
        capture = capture.split("      - name: bazel test //...\n", 1)[0]
        condition = (
            "if: failure() && steps.bazel_lock_check.outcome == 'failure' "
            "&& matrix.os == 'ubuntu-24.04' "
            "&& matrix.target == 'x86_64-unknown-linux-gnu'"
        )
        self.assertEqual(capture.count(condition), 2)
        self.assertNotIn("continue-on-error", capture)
        strict = workflow.split(
            "      - name: Check MODULE.bazel.lock is up to date\n", 1
        )[1]
        strict = strict.split(
            "      - name: Capture failed lock regeneration diagnostic\n", 1
        )[0]
        self.assertIn("id: bazel_lock_check", strict)
        self.assertIn("run: ./scripts/check-module-bazel-lock.sh", strict)
        self.assertNotIn("continue-on-error", strict)


if __name__ == "__main__":
    unittest.main()
