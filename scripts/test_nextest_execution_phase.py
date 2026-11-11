"""Actual file-identity controls with simulated Cargo/Nextest, not native tests."""

import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "phase_candidate", HERE / "nextest_binary_environment.py"
)
ENV = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ENV)


class ExecutionArgumentTests(unittest.TestCase):
    def test_build_selectors_stay_in_build_runtime_options_stay_in_execution(self):
        build = [
            "-p",
            "fixture",
            "--locked",
            "--offline",
            "--features=one,two",
            "--no-default-features",
            "--lib",
            "--cargo-profile",
            "dev-small",
            "--target-dir",
            "/exact/target",
            "-pother",
            "-Fmore",
        ]
        runtime = [
            "--cargo-metadata",
            "/owned/current.json",
            "--profile",
            "local",
            "-E",
            "test(original)",
            "--partition=hash:1/2",
            "--retries",
            "1",
            "--test-threads=2",
            "--no-fail-fast",
            "--run-ignored",
            "only",
        ]
        tail = ["--", "literal--locked", "--exact", "--skip", "-pnot-an-option"]
        command = ["cargo", "nextest", "run", *build, *runtime, *tail]
        original = command[:]
        execution, metadata, reason = ENV.listed_execution_arguments(
            command, "/owned/binaries.json"
        )
        self.assertEqual(command, original)
        self.assertEqual(
            execution,
            [
                "cargo",
                "nextest",
                "run",
                *runtime,
                "--binaries-metadata",
                "/owned/binaries.json",
                *tail,
            ],
        )
        self.assertEqual(metadata, "/owned/current.json")
        self.assertIsNone(reason)
        listing, reason = ENV.listing_arguments(command[3:], internal_metadata=True)
        self.assertIsNone(reason)
        self.assertEqual(listing[: len(build)], build)

    def test_unknown_configuration_target_and_missing_metadata_keep_original_path(self):
        prefix = ["cargo", "nextest", "run", "-p", "fixture"]
        for tail in (
            ["--config", "target.runner='custom'"],
            ["-Zunstable-options"],
            ["--target", "foreign"],
            ["--config-file", "custom.toml"],
            ["--future-flag", "value"],
            ["--cargo-metadata", "one", "--cargo-metadata", "two"],
            [],
            ["--cargo-metadata"],
            ["--cargo-metadata", "--"],
        ):
            with self.subTest(tail=tail):
                command = prefix + tail
                result, metadata, reason = ENV.listed_execution_arguments(
                    command, "/owned/list.json"
                )
                self.assertIsNone(result)
                self.assertIsNone(metadata)
                self.assertIsInstance(reason, str)


class ExecutionIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nextest-execution-phase-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.root / "target"
        self.target.mkdir()
        self.source = self.root / "main.rs"
        self.source.write_text("fn main() {}\n")
        self.manifest = self.root / "Cargo.toml"
        self.manifest.write_text('[package]\nname="fixture"\nversion="0.0.0"\n')
        self.helper = self.target / "fixture-tool"
        self.helper.write_bytes(b"Synthetic helper, not a native executable\n")
        self.helper.chmod(0o700)
        self.metadata = {
            "workspace_root": str(self.root),
            "workspace_members": ["fixture-id"],
            "packages": [
                {
                    "id": "fixture-id",
                    "name": "fixture",
                    "manifest_path": str(self.manifest),
                    "targets": [
                        {
                            "kind": ["bin"],
                            "name": "fixture-tool",
                            "src_path": str(self.source),
                        }
                    ],
                }
            ],
        }
        self.metadata_path = self.root / "current-metadata.json"
        self.metadata_path.write_text(json.dumps(self.metadata))
        self.listing = {
            "rust-build-meta": {
                "target-directory": str(self.target),
                "non-test-binaries": {
                    "fixture-id": [
                        {
                            "kind": "bin-exe",
                            "name": "fixture-tool",
                            "path": "fixture-tool",
                        }
                    ]
                },
            },
            "rust-binaries": {},
        }
        self.command = [
            "cargo",
            "nextest",
            "run",
            "--no-fail-fast",
            "-p",
            "fixture",
            "--locked",
            "-E",
            "test(original_case)",
            "--cargo-metadata",
            str(self.metadata_path),
        ]
        self.calls = []

    def replace_same_bytes(self, path):
        old = path.stat()
        replacement = path.with_name(path.name + ".replacement")
        replacement.write_bytes(path.read_bytes())
        replacement.chmod(old.st_mode & 0o777)
        os.utime(replacement, ns=(old.st_atime_ns, old.st_mtime_ns))
        os.replace(replacement, path)
        self.assertNotEqual(path.stat().st_ino, old.st_ino)

    def execute(self, *, mode="stable", native_exit=100, module=ENV):
        def fake_call(argv, **kwargs):
            self.calls.append(argv[:])
            if argv[2] == "list":
                self.assertIn("--locked", argv)
                self.assertEqual(argv[argv.index("-p") + 1], "fixture")
                kwargs["stdout"].write(json.dumps(self.listing).encode())
                return 0
            if "--binaries-metadata" not in argv:
                self.replace_same_bytes(self.helper)
            else:
                listed = Path(argv[argv.index("--binaries-metadata") + 1])
                self.assertEqual(json.loads(listed.read_bytes()), self.listing)
                self.assertEqual(argv[argv.index("-E") + 1], "test(original_case)")
                self.assertEqual(
                    kwargs["env"]["NEXTEST_BIN_EXE_fixture_tool"], str(self.helper)
                )
                if mode == "helper-replace":
                    self.replace_same_bytes(self.helper)
                elif mode == "helper-content":
                    self.helper.write_bytes(b"modified payload")
                elif mode == "listing-replace":
                    self.replace_same_bytes(listed)
                elif mode == "metadata-replace":
                    self.replace_same_bytes(self.metadata_path)
                elif mode == "source-change":
                    self.source.write_text("fn main() { panic!(); }\n")
            return native_exit

        with patch.object(module.subprocess, "call", side_effect=fake_call):
            status = module.run(self.command, self.metadata)
        paths = list(self.target.glob("hepta-nextest/*/receipt.json"))
        self.assertEqual(len(paths), 1)
        return status, json.loads(paths[0].read_bytes())

    def test_same_bytes_second_build_replacement_rejects_original_path(self):
        with patch.object(
            ENV,
            "listed_execution_arguments",
            return_value=(None, None, "exercise unchanged original-command path"),
        ):
            status, receipt = self.execute()
        self.assertEqual(status, 1)
        self.assertEqual(receipt["command_exit_code"], 100)
        self.assertEqual(receipt["status"], "BINARY_IDENTITY_REJECTED")
        before, after = (
            receipt["helpers"][0]["executable"],
            receipt["payloads_after"][0],
        )
        self.assertEqual(before["sha256"], after["sha256"])
        self.assertNotEqual(before["inode"], after["inode"])

    def test_listed_execution_keeps_bound_helper_identity_and_inner_failure(self):
        status, receipt = self.execute()
        self.assertEqual(status, 100)
        self.assertEqual(receipt["command"], self.command)
        self.assertEqual(
            receipt["status"], "LISTED_BINARIES_TERMINAL_OBSERVATIONS_MATCH"
        )
        self.assertEqual(
            receipt["payloads_after"], [receipt["helpers"][0]["executable"]]
        )
        self.assertEqual(
            receipt["execution_inputs_before"], receipt["execution_inputs_after"]
        )
        saved_cargo = receipt["execution_cargo_metadata"]
        self.assertEqual(
            Path(saved_cargo["path"]).read_bytes(), self.metadata_path.read_bytes()
        )
        self.assertEqual(saved_cargo, receipt["execution_cargo_metadata_after"])
        self.assertEqual(
            {key: saved_cargo[key] for key in ("bytes", "sha256")},
            receipt["execution_input_expected"][1],
        )
        self.assertEqual(len(self.calls), 2)
        self.assertNotIn("-p", self.calls[1])
        self.assertNotIn("--locked", self.calls[1])

    def test_listed_execution_keeps_success(self):
        status, receipt = self.execute(native_exit=0)
        self.assertEqual(status, 0)
        self.assertEqual(receipt["command_exit_code"], 0)
        self.assertEqual(receipt["execution_mode"], "official-listed-binaries")

    def test_same_bytes_helper_replacement_during_execution_still_rejects(self):
        status, receipt = self.execute(mode="helper-replace", native_exit=0)
        self.assertEqual(status, 1)
        self.assertEqual(receipt["status"], "BINARY_IDENTITY_REJECTED")
        self.assertIn("helper identity/bytes changed", receipt["error"])

    def test_changed_helper_content_still_rejects(self):
        status, receipt = self.execute(mode="helper-content", native_exit=0)
        self.assertEqual(status, 1)
        self.assertIn("helper identity/bytes changed", receipt["error"])

    def test_same_bytes_listing_replacement_during_execution_rejects(self):
        status, receipt = self.execute(mode="listing-replace", native_exit=0)
        self.assertEqual(status, 1)
        self.assertIn("execution metadata identity/bytes changed", receipt["error"])

    def test_same_bytes_cargo_metadata_replacement_during_execution_rejects(self):
        status, receipt = self.execute(mode="metadata-replace", native_exit=0)
        self.assertEqual(status, 1)
        self.assertIn("execution metadata identity/bytes changed", receipt["error"])

    def test_source_change_during_execution_still_rejects(self):
        status, receipt = self.execute(mode="source-change", native_exit=0)
        self.assertEqual(status, 1)
        self.assertIn("source changed during the original run", receipt["error"])

    def test_wrong_metadata_bytes_refuse_to_run_tests(self):
        self.metadata_path.write_text(json.dumps({"not": "the supplied inventory"}))

        def fake_call(argv, **kwargs):
            self.calls.append(argv)
            self.assertEqual(argv[2], "list")
            kwargs["stdout"].write(json.dumps(self.listing).encode())
            return 0

        with patch.object(ENV.subprocess, "call", side_effect=fake_call):
            self.assertEqual(ENV.run(self.command, self.metadata), 1)
        self.assertEqual(len(self.calls), 1)

    def test_listing_rewritten_after_parse_and_binding_refuses_execution(self):
        observe = ENV.file_observation
        changed = []

        def mutate(path, **kwargs):
            path = Path(path)
            if (
                not changed
                and path.name == "binaries.json"
                and path.parent.parent == self.target / "hepta-nextest"
            ):
                value = json.loads(path.read_bytes())
                value["rust-build-meta"]["target-directory"] = str(
                    self.root / "different-target"
                )
                path.write_text(json.dumps(value))
                changed.append(str(path))
            return observe(path, **kwargs)

        with patch.object(ENV, "file_observation", side_effect=mutate):
            status, receipt = self.execute(native_exit=0)
        self.assertEqual(status, 1)
        self.assertEqual(len(changed), 1)
        self.assertEqual(len(self.calls), 1)
        self.assertNotIn("command_exit_code", receipt)
        self.assertIn("metadata differs from validated bytes", receipt["error"])

    def test_cargo_metadata_rewritten_between_equality_read_and_observation_refuses_execution(
        self,
    ):
        observe = ENV.file_observation
        changed = []

        def mutate(path, **kwargs):
            path = Path(path)
            if not changed and path == self.metadata_path:
                value = json.loads(path.read_bytes())
                value["workspace_root"] = str(self.root / "different-workspace")
                path.write_text(json.dumps(value))
                changed.append(str(path))
            return observe(path, **kwargs)

        with patch.object(ENV, "file_observation", side_effect=mutate):
            status, receipt = self.execute(native_exit=0)
        self.assertEqual(status, 1)
        self.assertEqual(len(changed), 1)
        self.assertEqual(len(self.calls), 1)
        self.assertNotIn("command_exit_code", receipt)
        self.assertIn("metadata differs from validated bytes", receipt["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
