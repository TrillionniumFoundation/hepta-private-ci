"""Reject wrong toolchains before executing a workspace Cargo command."""
import contextlib
import io
import json
import subprocess
from pathlib import Path
import unittest
from unittest import mock

import verify_workspace_toolchain as toolchain

ROOT = Path(__file__).resolve().parents[2]


class WorkspaceToolchainTests(unittest.TestCase):
    def test_declared_pin_not_a_hardcoded_version_is_accepted(self):
        for pin in ("1.95.0", "1.96.0"):
            toolchain.verify_identity(pin, pin + "-x86_64-unknown-linux-gnu (directory override)",
                                      "release: " + pin + "\n", "release: " + pin + "\n")

    def test_runner_default_and_mismatching_compiler_or_cargo_are_rejected(self):
        good = ["1.95.0", "1.95.0-x86_64-unknown-linux-gnu", "release: 1.95.0\n", "release: 1.95.0\n"]
        for index, wrong in ((1, "stable-x86_64-unknown-linux-gnu"),
                             (2, "release: 1.98.0\n"), (3, "release: 1.98.0\n")):
            with self.subTest(index=index):
                args = good.copy()
                args[index] = wrong
                with self.assertRaises(ValueError):
                    toolchain.verify_identity(*args)

    def test_wrong_cwd_prevents_all_tool_execution(self):
        toolchain.verify_working_directory(ROOT / "codex-rs")
        with mock.patch.object(Path, "cwd", return_value=ROOT), \
             mock.patch.object(toolchain.subprocess, "check_output") as capture, \
             mock.patch.object(toolchain.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "codex-rs"):
                toolchain.main(["check"])
            capture.assert_not_called()
            run.assert_not_called()

    def test_non_exact_pin_prevents_all_tool_execution(self):
        with mock.patch.object(Path, "cwd", return_value=ROOT / "codex-rs"), \
             mock.patch.object(Path, "read_text", return_value='[toolchain]\nchannel = "stable"\n'), \
             mock.patch.object(toolchain.subprocess, "check_output") as capture, \
             mock.patch.object(toolchain.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "exact numeric"):
                toolchain.main(["check"])
            capture.assert_not_called()
            run.assert_not_called()

    def test_unapproved_subcommand_does_not_execute_tools(self):
        with mock.patch.object(toolchain.subprocess, "check_output") as capture, \
             mock.patch.object(toolchain.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "only workspace"):
                toolchain.main(["run"])
            capture.assert_not_called()
            run.assert_not_called()

    def test_version_mismatch_never_executes_qualification_command(self):
        identities = ["1.96.0-x86_64-unknown-linux-gnu", "release: 1.98.0\n",
                      "release: 1.96.0\n", "clippy identity"]
        with mock.patch.object(Path, "cwd", return_value=ROOT / "codex-rs"), \
             mock.patch.object(Path, "read_text", return_value='[toolchain]\nchannel = "1.96.0"\n'), \
             mock.patch.object(toolchain.subprocess, "check_output", side_effect=identities), \
             mock.patch.object(toolchain.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "rustc release"):
                toolchain.main(["test", "--locked", "-p", "codex-hepta-cognitive-types"])
            run.assert_not_called()

    def test_original_argv_pin_environment_and_failure_exit_are_preserved(self):
        identities = ["1.96.0-x86_64-unknown-linux-gnu", "release: 1.96.0\n",
                      "release: 1.96.0\n", "clippy identity"]
        arguments = ["clippy", "--manifest-path", "Cargo.toml", "--locked", "--all-targets", "--", "-D", "warnings"]
        with mock.patch.object(Path, "cwd", return_value=ROOT / "codex-rs"), \
             mock.patch.object(Path, "read_text", return_value='[toolchain]\nchannel = "1.96.0"\n'), \
             mock.patch.object(toolchain.subprocess, "check_output", side_effect=identities) as capture, \
             mock.patch.object(toolchain.subprocess, "run", return_value=mock.Mock(returncode=17)) as run, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(toolchain.main(arguments), 17)
            run.assert_called_once()
            self.assertEqual(run.call_args.args[0], ["cargo", *arguments])
            self.assertEqual(run.call_args.kwargs["cwd"], ROOT / "codex-rs")
            self.assertEqual(run.call_args.kwargs["env"]["RUSTUP_TOOLCHAIN"], "1.96.0")
            self.assertEqual(run.call_args.kwargs["env"]["RUSTUP_AUTO_INSTALL"], "0")
            self.assertFalse(run.call_args.kwargs["check"])
            for call in capture.call_args_list:
                self.assertEqual(call.kwargs["env"], run.call_args.kwargs["env"])


    def test_setup_installs_only_the_pin_and_its_declared_components(self):
        identities = ["1.96.0-x86_64-unknown-linux-gnu", "release: 1.96.0\n",
                      "release: 1.96.0\n", "clippy identity",
                      "rustfmt-x86_64-unknown-linux-gnu\nclippy-x86_64-unknown-linux-gnu\nrust-src\n"]
        manifest = '[toolchain]\nchannel = "1.96.0"\ncomponents = ["rustfmt", "clippy", "rust-src"]\n'
        with mock.patch.object(Path, "cwd", return_value=ROOT / "codex-rs"), \
             mock.patch.object(Path, "read_text", return_value=manifest), \
             mock.patch.object(toolchain.subprocess, "check_output", side_effect=identities), \
             mock.patch.object(toolchain.subprocess, "run") as run, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(toolchain.main([]), 0)
            run.assert_called_once()
            self.assertEqual(run.call_args.args[0], [
                "rustup", "toolchain", "install", "1.96.0", "--profile", "minimal", "--no-self-update",
                "--component", "rustfmt", "--component", "clippy", "--component", "rust-src",
            ])
            self.assertTrue(run.call_args.kwargs["check"])
            self.assertEqual(run.call_args.kwargs["env"]["RUSTUP_AUTO_INSTALL"], "0")

    def test_install_failure_prevents_identity_and_qualification_execution(self):
        with mock.patch.object(Path, "cwd", return_value=ROOT / "codex-rs"), \
             mock.patch.object(Path, "read_text", return_value='[toolchain]\nchannel = "1.96.0"\n'), \
             mock.patch.object(toolchain.subprocess, "check_output") as capture, \
             mock.patch.object(toolchain.subprocess, "run", side_effect=subprocess.CalledProcessError(17, ["rustup"])) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                toolchain.main([])
            run.assert_called_once()
            self.assertEqual(run.call_args.args[0][0], "rustup")
            capture.assert_not_called()

    def test_missing_installed_toolchain_cannot_trigger_implicit_install(self):
        with mock.patch.object(Path, "cwd", return_value=ROOT / "codex-rs"), \
             mock.patch.object(Path, "read_text", return_value='[toolchain]\nchannel = "1.96.0"\n'), \
             mock.patch.object(toolchain.subprocess, "check_output", side_effect=subprocess.CalledProcessError(1, ["rustup"])) as capture, \
             mock.patch.object(toolchain.subprocess, "run") as run:
            with self.assertRaises(subprocess.CalledProcessError):
                toolchain.main(["check"])
            self.assertEqual(capture.call_args.kwargs["env"]["RUSTUP_AUTO_INSTALL"], "0")
            run.assert_not_called()

    def test_missing_declared_component_prevents_qualification_execution(self):
        identities = ["1.96.0-x86_64-unknown-linux-gnu", "release: 1.96.0\n",
                      "release: 1.96.0\n", "clippy identity", "clippy-x86_64-unknown-linux-gnu\n"]
        manifest = '[toolchain]\nchannel = "1.96.0"\ncomponents = ["clippy", "rustfmt", "rust-src"]\n'
        with mock.patch.object(Path, "cwd", return_value=ROOT / "codex-rs"), \
             mock.patch.object(Path, "read_text", return_value=manifest), \
             mock.patch.object(toolchain.subprocess, "check_output", side_effect=identities), \
             mock.patch.object(toolchain.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "component is not installed"):
                toolchain.main(["test"])
            run.assert_not_called()

    def test_malformed_component_declarations_are_rejected_before_tools(self):
        for components in ("clippy", [1], ["--help"], ["clippy;echo"]):
            manifest = '[toolchain]\nchannel = "1.96.0"\ncomponents = ' + json.dumps(components) + "\n"
            with self.subTest(components=components), \
                 mock.patch.object(Path, "cwd", return_value=ROOT / "codex-rs"), \
                 mock.patch.object(Path, "read_text", return_value=manifest), \
                 mock.patch.object(toolchain.subprocess, "check_output") as capture, \
                 mock.patch.object(toolchain.subprocess, "run") as run:
                with self.assertRaisesRegex(ValueError, "component names"):
                    toolchain.main(["check"])
                capture.assert_not_called()
                run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
