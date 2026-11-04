"""Real byte/Git transfer rejection tests with synthetic CI command receipts.

These fixtures do not compile a Hepta image or execute installed-profile/model
controls. Native execution remains the separate workflow's actual 14+8 gate.
"""

import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from scripts import hepta_ci_installed_cell as target
from scripts import hepta_ci_installed_controls as execution


def json_file(path, value):
    path.write_text(json.dumps(value))


def repository(path):
    (path / "codex-rs").mkdir(parents=True)
    (path / "codex-rs/Cargo.lock").write_text("synthetic locked input\n")
    for command in (
        ["init", "-q"],
        ["add", "."],
        [
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "core.hooksPath=/dev/null",
            "commit",
            "-qm",
            "fixture",
        ],
    ):
        subprocess.run(["git", *command], cwd=path, check=True, capture_output=True)
    return target.identity(repository=path)


class InstalledArtifactTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.temporary = Path(directory.name)
        self.root = self.temporary / "source"
        self.before = repository(self.root)
        previous = Path.cwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, previous)
        self.output = self.temporary / "observations"
        self.output.mkdir()
        self.build_target = self.temporary / "target"
        binary = self.build_target / "debug/hepta-neural-agentd"
        binary.parent.mkdir(parents=True)
        shutil.copyfile(Path(sys.executable).resolve(), binary)
        binary.chmod(0o555)
        self.environment = dict(
            GITHUB_ACTIONS="true",
            RUNNER_ENVIRONMENT="github-hosted",
            RUNNER_OS="Linux",
            RUNNER_ARCH="X64",
            GITHUB_REPOSITORY=target.REPOSITORY,
            GITHUB_RUN_ID="123",
            GITHUB_RUN_ATTEMPT="2",
            GITHUB_JOB="cell-host-v2",
            GITHUB_WORKFLOW_REF=target.REPOSITORY
            + "/"
            + target.WORKFLOW
            + "@refs/pull/1/merge",
            GITHUB_WORKFLOW_SHA="a" * 40,
            GITHUB_SHA="b" * 40,
            SOURCE_SHA=self.before["commit"],
            TESTED_SHA=self.before["commit"],
            BASE_SHA=self.before["commit"],
            HEPTA_CI_LANE="source-head",
            RUSTUP_TOOLCHAIN="1.96.0",
            CARGO_TARGET_DIR=str(self.build_target),
        )
        context = mock.patch.dict(os.environ, self.environment)
        context.start()
        self.addCleanup(context.stop)
        caller = mock.patch.object(target.os, "geteuid", return_value=1001)
        caller.start()
        self.addCleanup(caller.stop)
        self.source = target.candidate()
        self.cli = self.output / "cli.json"
        self.make_receipt(self.cli, target.CLI_COMMAND, 3)
        actual = subprocess.check_output

        def commands(command, **kwargs):
            if command[0] == "cargo":
                return json.dumps(
                    {
                        "workspace_root": str(self.root / "codex-rs"),
                        "target_directory": str(self.build_target),
                    }
                ).encode()
            if command == ["rustc", "-vV"]:
                return b"release: 1.96.0\nhost: x86_64-unknown-linux-gnu\n"
            return actual(command, **kwargs)

        self.artifact = self.temporary / "artifact"
        with mock.patch.object(target.subprocess, "check_output", side_effect=commands):
            target.pack(self.artifact, self.cli)
        os.environ["GITHUB_JOB"] = "cell-installed-host-v3"
        self.native = self.temporary / "received/hepta-neural-agentd"
        self.imported = self.output / "imported.json"

    def make_receipt(
        self, path, command, count, *, code=0, source=None, before=None, text=None
    ):
        source, before = source or self.source, before or self.before
        log = path.with_suffix(".raw.log")
        if text is None:
            text = "".join(
                f"test_case_{i} (__main__.Fixture.test_case_{i}) ... ok\n"
                for i in range(count)
            )
            text += f"\nRan {count} tests in 0.001s\n\nOK\n"
        log.write_text(text)
        record = dict(
            schema_version=1,
            status="passed" if code == 0 else "failed",
            source_sha=source["source_sha"],
            tested_sha=source["tested_sha"],
            base_sha=source["base_sha"] or "",
            lane="source-head",
            before=before,
            after=before,
            command=command,
            minimum_tests=count,
            run_id="123",
            run_attempt="2",
            job=os.environ["GITHUB_JOB"],
            exit_code=code,
            command_exit_code=code,
            returncode=code,
            timed_out=False,
            output_limit_exceeded=False,
            observed_passed_tests=count,
            observed_failed_tests=0,
            log_file=log.name,
            log_bytes=log.stat().st_size,
            log_sha256=target.file_record(log)["sha256"],
        )
        json_file(path, record)

    def refresh(self):
        manifest = target.read(self.artifact / "artifact.json")
        manifest["files"] = {
            name: target.file_record(self.artifact / name) for name in target.FILES
        }
        json_file(self.artifact / "artifact.json", manifest)

    def verify(self):
        target.verify(self.artifact, self.native, self.imported)

    def test_roundtrip_retains_exact_binary_original_receipt_and_nonqualification(self):
        self.verify()
        result = target.read(self.imported)
        self.assertEqual(result["binary"], target.native_record(self.native))
        self.assertEqual(result["candidate"], self.source)
        self.assertIs(result["installed_controls_executed"], False)
        self.assertIs(result["model_qualified"], False)
        self.assertIs(result["pn0_closed"], False)

    def test_other_run_cannot_supply_native_image(self):
        with (
            mock.patch.dict(os.environ, GITHUB_RUN_ID="124"),
            self.assertRaisesRegex(ValueError, "identity"),
        ):
            self.verify()

    def test_other_source_tree_cannot_be_relabelled(self):
        value = target.read(self.artifact / "artifact.json")
        value["source_identity"]["tree"] = "c" * 40
        json_file(self.artifact / "artifact.json", value)
        with self.assertRaisesRegex(ValueError, "identity"):
            self.verify()

    def test_rehashed_different_lock_cannot_replace_checkout_lock(self):
        (self.artifact / "Cargo.lock").write_text("different lock\n")
        self.refresh()
        with self.assertRaisesRegex(ValueError, "lock differs"):
            self.verify()

    def test_rehashed_compressed_substitution_cannot_replace_native(self):
        (self.artifact / "native.gz").write_bytes(gzip.compress(b"different image"))
        self.refresh()
        with self.assertRaises(ValueError):
            self.verify()

    def test_wrong_compile_command_is_not_native_cli_evidence(self):
        value = target.read(self.artifact / "cli-process.json")
        value["command"] = ["true"]
        json_file(self.artifact / "cli-process.json", value)
        self.refresh()
        with self.assertRaisesRegex(ValueError, "native command"):
            self.verify()

    def test_zero_tests_cannot_become_passing_image_evidence(self):
        self.rewrite_cli_log("\nRan 0 tests in 0.001s\n\nOK\n")
        with self.assertRaisesRegex(ValueError, "controls"):
            self.verify()

    def test_skipped_cli_controls_cannot_supply_image_evidence(self):
        self.rewrite_cli_log("\nRan 3 tests in 0.001s\n\nOK (skipped=1)\n")
        with self.assertRaisesRegex(ValueError, "controls"):
            self.verify()

    def rewrite_cli_log(self, text):
        log = self.artifact / "cli-process.log"
        log.write_text(text)
        value = target.read(self.artifact / "cli-process.json")
        value.update(
            log_bytes=log.stat().st_size, log_sha256=target.file_record(log)["sha256"]
        )
        json_file(self.artifact / "cli-process.json", value)
        self.refresh()

    def test_unknown_artifact_file_is_rejected(self):
        (self.artifact / "unexpected").write_text("not in original bundle")
        with self.assertRaisesRegex(ValueError, "complete single"):
            self.verify()

    def test_decompression_enforces_original_image_limit(self):
        with (
            mock.patch.object(target, "MAXIMUM_IMAGE", 16),
            self.assertRaisesRegex(ValueError, "limit"),
        ):
            self.verify()

    def test_actual_checkout_change_during_transfer_is_rejected(self):
        original = gzip.open

        def mutate(*args, **kwargs):
            (self.root / "codex-rs/Cargo.lock").write_text("changed during import\n")
            return original(*args, **kwargs)

        with (
            mock.patch.object(target.gzip, "open", side_effect=mutate),
            self.assertRaisesRegex(ValueError, "checkout changed"),
        ):
            self.verify()

    def test_explicit_installed_reader_rejects_skip_even_with_extra_passes(self):
        record = self.output / "installed.json"
        text = "".join(
            f"test_case_{i} (__main__.Fixture.test_case_{i}) ... ok\n" for i in range(8)
        )
        text += "\nRan 9 tests in 0.001s\n\nOK (skipped=1)\n"
        self.make_receipt(record, ["synthetic-control"], 8, text=text)
        with self.assertRaisesRegex(ValueError, "skipped or incomplete"):
            target.receipt(record, self.source, 8, exact=True)

    def test_ci_rejects_root_local_and_wrong_architecture_contexts(self):
        with (
            mock.patch.object(target.os, "geteuid", return_value=0),
            self.assertRaises(ValueError),
        ):
            target.ci("cell-installed-host-v3")
        for environment in (
            {"GITHUB_ACTIONS": "false"},
            {"RUNNER_ARCH": "ARM64"},
            {"GITHUB_JOB": "other"},
        ):
            with (
                mock.patch.dict(os.environ, environment),
                self.assertRaises(ValueError),
            ):
                target.ci("cell-installed-host-v3")

    def test_placeholder_chain_pin_cannot_dispatch_controls(self):
        with self.assertRaisesRegex(ValueError, "explicit final Chain"):
            execution.controls(
                self.root,
                "UNSET_FINAL_CHAIN_COMMIT",
                "0" * 40,
                self.native,
                self.native,
                self.imported,
                self.output,
            )

    def control_report(self, *, first_code=0, mutate_binary=False):
        self.verify()
        chain = self.temporary / "chain"
        repository(chain)
        (chain / "trillionnium").mkdir()
        shutil.copyfile(
            chain / "codex-rs/Cargo.lock", chain / "trillionnium/Cargo.lock"
        )
        subprocess.run(["git", "add", "."], cwd=chain, check=True, capture_output=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "-c",
                "core.hooksPath=/dev/null",
                "commit",
                "-qm",
                "chain lock",
            ],
            cwd=chain,
            check=True,
            capture_output=True,
        )
        chain_before = target.identity(repository=chain)
        chain_source = target.candidate_plan(
            source=chain_before["commit"],
            tested=chain_before["commit"],
            lane="source-head",
            repository=chain,
        )
        self.make_receipt(
            self.output / "chain-build.json",
            target.BUILD_COMMAND,
            0,
            source=chain_source,
            before=chain_before,
        )
        cell = self.temporary / "native-cell"
        shutil.copyfile(Path(sys.executable).resolve(), cell)
        cell.chmod(0o755)
        calls = []

        def command(path, argv, *, minimum_tests):
            calls.append(minimum_tests)
            code = first_code if len(calls) == 1 else 0
            self.make_receipt(path, argv, minimum_tests, code=code)
            if mutate_binary and len(calls) == 2:
                with cell.open("ab") as stream:
                    stream.write(b"changed actual image bytes")
            return code

        with mock.patch.object(execution, "run", side_effect=command):
            code = execution.controls(
                chain,
                chain_before["commit"],
                chain_before["tree"],
                self.native,
                cell,
                self.imported,
                self.output,
            )
        return code, calls, target.read(self.output / "installed-controls.json")

    def test_complete_two_control_receipts_keep_every_qualification_false(self):
        code, calls, report = self.control_report()
        self.assertEqual((code, calls, report["status"]), (0, [14, 8], "passed"))
        for name in (
            "native_pair_qualification",
            "pn0_closed",
            "model_qualified",
            "final_use_qualified",
            "production_activation",
        ):
            self.assertIs(report[name], False)

    def test_original_failure_is_retained_even_when_installed_controls_pass(self):
        code, calls, report = self.control_report(first_code=7)
        self.assertEqual(
            (code, calls, report["status"], report["command_statuses"]),
            (1, [14, 8], "failed", [7, 0]),
        )
        self.assertEqual(
            target.read(self.output / "original-handoff.json")["command_exit_code"], 7
        )

    def test_native_byte_change_after_successful_controls_is_rejected(self):
        code, calls, report = self.control_report(mutate_binary=True)
        self.assertEqual((code, calls, report["status"]), (1, [14, 8], "failed"))
        self.assertNotEqual(report["binaries_before"], report["binaries_after"])


if __name__ == "__main__":
    unittest.main()
