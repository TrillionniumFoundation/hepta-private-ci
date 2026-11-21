#!/usr/bin/env python3
"""Exercise toolchain selection and fail-closed environment publication."""

import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import hepta_ci_toolchain


class WorkspaceToolchainTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        source = self.root / "codex-rs/rust-toolchain.toml"
        source.parent.mkdir()
        self.contents = (
            '[toolchain]\nchannel = "1.96.0"\n'
            'components = ["clippy", "rustfmt", "rust-src"]\n'
        )
        source.write_text(self.contents, encoding="utf-8")
        self.source = source
        self.github_env = self.root / "github-env"
        self.github_env.write_text("EXISTING=retained\n", encoding="utf-8")

    def test_workspace_pin_controls_install_and_root_command_environment(self):
        version = "rustc 1.96.0 (fixture)\nrelease: 1.96.0\n"
        with (
            patch.dict("os.environ", {"RUSTUP_TOOLCHAIN": "1.95.0"}),
            patch.object(subprocess, "run") as run,
            patch.object(subprocess, "check_output", return_value=version) as check,
        ):
            receipt = hepta_ci_toolchain.install(
                self.root, self.github_env, ["llvm-tools-preview", "clippy"]
            )
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
                "llvm-tools-preview",
                "--component",
                "rust-src",
                "--component",
                "rustfmt",
            ],
            cwd=self.root,
            check=True,
        )
        self.assertEqual(check.call_args.kwargs["cwd"], self.root)
        self.assertEqual(check.call_args.kwargs["env"]["RUSTUP_TOOLCHAIN"], "1.96.0")
        self.assertEqual(
            self.github_env.read_text(), "EXISTING=retained\nRUSTUP_TOOLCHAIN=1.96.0\n"
        )
        self.assertEqual(
            receipt["source_sha256"], hashlib.sha256(self.contents.encode()).hexdigest()
        )
        self.assertEqual(receipt["rustc_version"], version)

    def test_actual_compiler_mismatch_never_publishes_environment(self):
        with (
            patch.object(subprocess, "run"),
            patch.object(subprocess, "check_output", return_value="release: 1.95.0\n"),
            self.assertRaisesRegex(ValueError, "installed rustc release differs"),
        ):
            hepta_ci_toolchain.install(self.root, self.github_env, [])
        self.assertEqual(self.github_env.read_text(), "EXISTING=retained\n")

    def test_install_failure_never_probes_or_publishes(self):
        with (
            patch.object(
                subprocess,
                "run",
                side_effect=subprocess.CalledProcessError(1, "rustup"),
            ),
            patch.object(subprocess, "check_output") as check,
            self.assertRaises(subprocess.CalledProcessError),
        ):
            hepta_ci_toolchain.install(self.root, self.github_env, [])
        check.assert_not_called()
        self.assertEqual(self.github_env.read_text(), "EXISTING=retained\n")

    def test_unpinned_source_never_installs(self):
        for channel in ("stable", "1.96", "nightly", "1.96.0\\nINJECT=1"):
            with self.subTest(channel=channel):
                self.source.write_text(self.contents.replace("1.96.0", channel))
                with (
                    patch.object(subprocess, "run") as run,
                    self.assertRaises(ValueError),
                ):
                    hepta_ci_toolchain.install(self.root, self.github_env, [])
                run.assert_not_called()
        self.assertEqual(self.github_env.read_text(), "EXISTING=retained\n")


if __name__ == "__main__":
    unittest.main()
