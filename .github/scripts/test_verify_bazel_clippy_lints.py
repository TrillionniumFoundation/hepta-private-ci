"""Exercise the Cargo-to-Bazel lint verifier with supported and invalid manifests."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).with_name("verify_bazel_clippy_lints.py")
PREFIX = "build:clippy --@rules_rust//rust/settings:clippy_flag="


class LintSynchronizationTests(unittest.TestCase):
    def run_verifier(self, cargo_lints, bazel_lints):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cargo = root / "Cargo.toml"
            bazel = root / ".bazelrc"
            cargo.write_text("[workspace.lints.clippy]\n" + cargo_lints)
            bazel.write_text("".join(PREFIX + flag + "\n" for flag in bazel_lints))
            return subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--cargo-toml",
                    str(cargo),
                    "--bazelrc",
                    str(bazel),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )

    def test_prioritized_group_and_string_level_match_actual_bazel_flags(self):
        result = self.run_verifier(
            'correctness = { level = "deny", priority = -1 }\n'
            'unwrap_used = "deny"\nidentity_op = "warn"\n',
            [
                "--deny=clippy::correctness",
                "-Dclippy::unwrap_used",
                "--warn=clippy::identity_op",
            ],
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_level_mismatch_remains_failure_for_table_lint(self):
        result = self.run_verifier(
            'correctness = { level = "deny", priority = -1 }\n',
            ["--warn=clippy::correctness"],
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("Mismatched lint levels", result.stderr)

    def test_invalid_tables_do_not_bypass_synchronization(self):
        for value in [
            "{ priority = -1 }",
            '{ level = "deny", priority = true }',
            '{ level = "deny", priority = "low" }',
            '{ level = "deny", unexpected = 1 }',
            '{ level = "unknown", priority = -1 }',
        ]:
            with self.subTest(value=value):
                result = self.run_verifier(
                    "correctness = " + value + "\n",
                    ["--deny=clippy::correctness"],
                )
                self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
