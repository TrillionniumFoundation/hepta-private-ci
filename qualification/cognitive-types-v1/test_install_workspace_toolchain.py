"""Exercise explicit component setup without weakening qualification checks."""

from pathlib import Path
import unittest
from unittest import mock

import install_workspace_toolchain as installer
import verify_workspace_toolchain as verifier

ROOT = Path(__file__).resolve().parents[2]
DECLARED = (
    '[toolchain]\nchannel = "1.96.0"\ncomponents = ["clippy", "rustfmt", "rust-src"]\n'
)


class InstallWorkspaceToolchainTests(unittest.TestCase):
    def test_missing_clippy_still_fails_verification_until_explicit_setup(self):
        installed = False

        def identity(command, **_kwargs):
            if command == ["cargo", "clippy", "--version"]:
                if not installed:
                    raise installer.subprocess.CalledProcessError(1, command)
                return "clippy identity"
            if command == ["rustup", "show", "active-toolchain"]:
                return "1.96.0-x86_64-unknown-linux-gnu"
            return "release: 1.96.0\n"

        def install(command, **_kwargs):
            nonlocal installed
            self.assertEqual(command[:4], ["rustup", "toolchain", "install", "1.96.0"])
            installed = True
            return mock.Mock(returncode=0)

        with (
            mock.patch.object(Path, "cwd", return_value=ROOT / "codex-rs"),
            mock.patch.object(Path, "read_text", return_value=DECLARED),
            mock.patch.object(installer.subprocess, "run", side_effect=install),
            mock.patch.object(
                verifier.subprocess, "check_output", side_effect=identity
            ),
        ):
            with self.assertRaises(installer.subprocess.CalledProcessError):
                verifier.main([])
            self.assertEqual(installer.main(), 0)
            self.assertEqual(verifier.main([]), 0)

    def test_installs_exact_declared_pin_and_components_without_changing_default(self):
        with (
            mock.patch.object(Path, "cwd", return_value=ROOT / "codex-rs"),
            mock.patch.object(Path, "read_text", return_value=DECLARED),
            mock.patch.object(
                installer.subprocess, "run", return_value=mock.Mock(returncode=0)
            ) as run,
        ):
            self.assertEqual(installer.main(), 0)
            run.assert_called_once_with(
                [
                    "rustup",
                    "toolchain",
                    "install",
                    "1.96.0",
                    "--profile",
                    "minimal",
                    "--no-self-update",
                    "--component",
                    "clippy",
                    "--component",
                    "rustfmt",
                    "--component",
                    "rust-src",
                ],
                check=False,
            )

    def test_installation_failure_remains_failure(self):
        with (
            mock.patch.object(Path, "cwd", return_value=ROOT / "codex-rs"),
            mock.patch.object(Path, "read_text", return_value=DECLARED),
            mock.patch.object(
                installer.subprocess, "run", return_value=mock.Mock(returncode=17)
            ),
        ):
            self.assertEqual(installer.main(), 17)

    def test_wrong_working_directory_prevents_installation(self):
        with (
            mock.patch.object(Path, "cwd", return_value=ROOT),
            mock.patch.object(installer.subprocess, "run") as run,
        ):
            with self.assertRaisesRegex(ValueError, "codex-rs"):
                installer.main()
            run.assert_not_called()

    def test_invalid_pin_or_missing_required_components_prevents_installation(self):
        invalid = [
            DECLARED.replace('"1.96.0"', '"stable"'),
            DECLARED.replace('"clippy", ', ""),
            DECLARED.replace('"rustfmt", ', ""),
            DECLARED.replace('"rust-src"', '"--help"'),
            DECLARED.replace('"rust-src"', "false"),
            DECLARED.replace('["clippy", "rustfmt", "rust-src"]', '"clippy,rustfmt"'),
        ]
        for declared in invalid:
            with (
                self.subTest(declared=declared),
                mock.patch.object(Path, "cwd", return_value=ROOT / "codex-rs"),
                mock.patch.object(Path, "read_text", return_value=declared),
                mock.patch.object(installer.subprocess, "run") as run,
            ):
                with self.assertRaises(ValueError):
                    installer.main()
                run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
