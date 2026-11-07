"""Boundary tests for official helper bindings and unchanged Nextest arguments.

No synthetic file here is represented as a native build or native qualification.
The existing Cargo/Nextest tests and cargo-bin subprocess controls remain separate.
"""

import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "nextest_binary_environment", Path(__file__).with_name("nextest_binary_environment.py")
)
ENV = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ENV)


class ArgumentBoundaryTests(unittest.TestCase):
    def test_full_selection_features_target_config_and_filters_are_opaque(self):
        args = ["--workspace", "--locked", "--exclude", "excluded", "-F", "a,b",
                "--no-default-features", "--target", "aarch64-apple-darwin",
                "--target-dir=custom", "--cargo-profile", "ci", "-E", "deps(example)",
                "--config-file", "custom.toml", "--tool-config-file", "x:/custom.toml",
                "--config", "target.aarch64-apple-darwin.runner='remote'",
                "--run-ignored", "only", "--partition=hash:1/2", "--profile", "local",
                "--retries", "3", "-j2", "--no-fail-fast", "--status-level", "all",
                "--", "literal--retries", "--exact", "--skip", "-j4"]
        original = args[:]
        listing, reason = ENV.listing_arguments(args)
        self.assertIsNone(reason)
        self.assertEqual(args, original)
        self.assertEqual(listing, args[:25] + ["--list-type", "binaries-only", "--message-format", "json"] + args[31:])

    def test_run_only_flags_do_not_consume_the_next_shared_argument(self):
        args = ["--retries=2", "--fail-fast", "--max-fail", "3", "--no-capture",
                "--stress-count", "5", "--success-output=immediate", "--message-format",
                "libtest-json", "--message-format-version=0.1", "--no-input-handler",
                "-pfoo", "-Fbar", "-Etest(name)", "-Pci", "-Zunstable-options", "-r"]
        listing, reason = ENV.listing_arguments(args)
        self.assertIsNone(reason)
        self.assertEqual(listing[:-4], args[-6:])

    def test_unknown_options_and_reuse_are_not_silently_approximated(self):
        for args in (["--future-flag", "x"], ["--archive-file", "old.tar.zst"],
                     ["--cargo-metadata", "old.json"], ["--workspace-remap=/new"],
                     ["--binaries-metadata", "old.json"], ["--retries"], ["-E", "--"]):
            with self.subTest(args=args):
                listing, reason = ENV.listing_arguments(args)
                self.assertIsNone(listing)
                self.assertIsInstance(reason, str)

    def test_internal_scoped_metadata_is_preserved_for_the_official_list(self):
        args = ["-p", "a", "--cargo-metadata", "/current.json", "--locked", "--", "one", "--exact"]
        listing, reason = ENV.listing_arguments(args, internal_metadata=True)
        self.assertIsNone(reason)
        self.assertEqual(listing[:5], args[:5])
        self.assertEqual(listing[-3:], args[-3:])

    def test_ownership_inventory_never_replaces_nextest_graph_or_selection(self):
        args = ["-p", "a", "--target-dir", "different", "--features", "f", "--target", "foreign",
                "--locked", "--manifest-path", "/workspace/Cargo.toml", "--config", "build.target='foreign'",
                "-Zunstable-options", "-E", "deps(a)", "--", "--manifest-path", "not-an-option"]
        self.assertEqual(ENV.ownership_metadata_arguments(args),
                         ["cargo", "metadata", "--no-deps", "--format-version=1", "--locked",
                          "--manifest-path", "/workspace/Cargo.toml", "--config", "build.target='foreign'", "-Zunstable-options"])


class IdentityBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.root / "target"
        self.target.mkdir()
        self.src = self.root / "src.rs"
        self.src.write_text("fn main() {}\n")
        self.manifest = self.root / "Cargo.toml"
        self.manifest.write_text('[package]\nname="fixture"\nversion="0.0.0"\n')
        self.metadata = {"workspace_root": str(self.root), "workspace_members": ["fixture-id"],
                         "packages": [{"id": "fixture-id", "name": "fixture",
                                       "manifest_path": str(self.manifest), "targets": []}]}
        self.listing = {"rust-build-meta": {"target-directory": str(self.target),
                                           "non-test-binaries": {"fixture-id": []}}}

    def add(self, name, payload=b"synthetic fixture bytes", path=None):
        artifact = self.target / (path or name)
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_bytes(payload)
        artifact.chmod(0o700)
        self.metadata["packages"][0]["targets"].append({"name": name, "kind": ["bin"], "src_path": str(self.src)})
        self.listing["rust-build-meta"]["non-test-binaries"]["fixture-id"].append(
            {"name": name, "kind": "bin-exe", "path": str(artifact.relative_to(self.target))})
        return artifact

    def test_empty_scoped_build_does_not_require_or_guess_three_helpers(self):
        (self.target / "codex").write_bytes(b"unreported stale binary")
        child, evidence = ENV.bind_environment(self.listing, self.metadata, {"UNCHANGED": "value"})
        self.assertEqual(child, {"UNCHANGED": "value"})
        self.assertEqual(evidence, [])

    def test_reported_target_path_and_existing_valid_value_are_preserved(self):
        artifact = self.add("fixture-tool", path="custom-target/release/actual-name.exe")
        inherited = {"CARGO_BIN_EXE_fixture-tool": str(artifact), "UNCHANGED": "value"}
        child, evidence = ENV.bind_environment(self.listing, self.metadata, inherited)
        self.assertEqual(child["CARGO_BIN_EXE_fixture-tool"], str(artifact))
        self.assertEqual(child["NEXTEST_BIN_EXE_fixture_tool"], str(artifact))
        self.assertEqual(inherited, {"CARGO_BIN_EXE_fixture-tool": str(artifact), "UNCHANGED": "value"})
        self.assertEqual(evidence[0]["official_artifact"]["path"], "custom-target/release/actual-name.exe")
        self.assertIn("git_blob", evidence[0]["target_source"])

    def test_first_present_invalid_cannot_be_masked_by_later_valid_value(self):
        artifact = self.add("fixture-tool")
        for invalid in ("", "relative", str(self.root / "missing"), str(self.root)):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ENV.BinaryEnvironmentError):
                    ENV.bind_environment(self.listing, self.metadata,
                        {"CARGO_BIN_EXE_fixture-tool": invalid, "NEXTEST_BIN_EXE_fixture_tool": str(artifact)})

    def test_same_bytes_at_an_unrelated_explicit_path_remain_a_conflict(self):
        artifact = self.add("fixture")
        other = self.root / "historical"
        other.write_bytes(artifact.read_bytes())
        other.chmod(0o700)
        with self.assertRaises(ENV.BinaryEnvironmentError):
            ENV.bind_environment(self.listing, self.metadata, {"NEXTEST_BIN_EXE_fixture": str(other)})

    def test_duplicate_names_and_normalized_aliases_are_rejected(self):
        self.add("fixture-tool")
        self.add("fixture_tool")
        with self.assertRaisesRegex(ENV.BinaryEnvironmentError, "ambiguous binary alias"):
            ENV.bind_environment(self.listing, self.metadata, {})

    def test_windows_case_folding_preserves_existing_invalid_first_value(self):
        artifact = self.add("fixture-tool")
        with self.assertRaises(ENV.BinaryEnvironmentError):
            ENV.bind_environment(self.listing, self.metadata,
                {"CARGO_BIN_EXE_FIXTURE-TOOL": "", "NEXTEST_BIN_EXE_fixture_tool": str(artifact)}, windows=True)
        child, _ = ENV.bind_environment(self.listing, self.metadata,
                                       {"NEXTEST_BIN_EXE_FIXTURE-TOOL": str(artifact)}, windows=True)
        self.assertNotIn("NEXTEST_BIN_EXE_fixture-tool", child)
        self.assertEqual(child["NEXTEST_BIN_EXE_FIXTURE_TOOL"], str(artifact))

    def test_windows_case_colliding_binary_names_are_rejected(self):
        self.add("Fixture")
        self.add("fixture")
        with self.assertRaisesRegex(ENV.BinaryEnvironmentError, "ambiguous binary alias"):
            ENV.bind_environment(self.listing, self.metadata, {}, windows=True)

    def test_foreign_package_missing_file_and_escaped_target_are_rejected(self):
        artifact = self.add("fixture")
        artifact.unlink()
        with self.assertRaises(FileNotFoundError):
            ENV.bind_environment(self.listing, self.metadata, {})
        artifact.write_bytes(b"synthetic")
        artifact.chmod(0o700)
        self.metadata["workspace_members"] = []
        with self.assertRaisesRegex(ENV.BinaryEnvironmentError, "current workspace member"):
            ENV.bind_environment(self.listing, self.metadata, {})
        self.metadata["workspace_members"] = ["fixture-id"]
        self.listing["rust-build-meta"]["non-test-binaries"]["fixture-id"][0]["path"] = "../src.rs"
        with self.assertRaisesRegex(ENV.BinaryEnvironmentError, "invalid official artifact path"):
            ENV.bind_environment(self.listing, self.metadata, {})

    def test_source_snapshot_covers_dirty_declared_input_without_requiring_git(self):
        self.add("fixture")
        before = ENV.source_observation(self.metadata)
        self.src.write_text("fn main() { panic!(); }\n")
        after = ENV.source_observation(self.metadata)
        self.assertNotEqual(before, after)
        self.assertIsNone(before["git"])

    def test_fresh_lock_creation_is_recorded_without_authorizing_existing_lock_changes(self):
        before = ENV.source_observation(self.metadata)
        lock = self.root / "Cargo.lock"
        lock.write_text("# generated lock\nversion = 4\n")
        after = ENV.source_observation(self.metadata)
        generated = ENV.validate_official_build_source(before, after)
        self.assertEqual(generated, ENV.file_observation(lock))
        self.assertIsNone(ENV.validate_official_build_source(after, after))
        lock.write_text("# changed existing lock\nversion = 4\n")
        with self.assertRaises(ENV.BinaryEnvironmentError):
            ENV.validate_official_build_source(after, ENV.source_observation(self.metadata))

    def test_new_lock_does_not_hide_other_declared_source_or_git_changes(self):
        before = ENV.source_observation(self.metadata)
        (self.root / "Cargo.lock").write_text("# generated lock\nversion = 4\n")
        after = ENV.source_observation(self.metadata)
        changed_git = {**after, "git": {"tracked_delta_sha256": "different"}}
        with self.assertRaises(ENV.BinaryEnvironmentError):
            ENV.validate_official_build_source(before, changed_git)
        self.manifest.write_text("[package]\nname = 'changed'\nversion = '0.0.0'\n")
        with self.assertRaises(ENV.BinaryEnvironmentError):
            ENV.validate_official_build_source(before, ENV.source_observation(self.metadata))

    @unittest.skipIf(os.name == "nt", "symlink setup requires separate Windows permission")
    def test_new_lock_cannot_redirect_to_an_external_file(self):
        before = ENV.source_observation(self.metadata)
        external = self.root / "external-lock"
        external.write_text("version = 4\n")
        (self.root / "Cargo.lock").symlink_to(external)
        with self.assertRaises(ENV.BinaryEnvironmentError):
            ENV.validate_official_build_source(before, ENV.source_observation(self.metadata))

    def test_original_run_argv_and_failure_exit_are_preserved(self):
        artifact = self.add("fixture-tool")
        command = ["cargo", "nextest", "run", "--no-fail-fast", "-p", "fixture",
                   "--locked", "--features", "selected", "-E", "test(original)",
                   "--retries", "2", "--status-level", "all", "--", "literal", "--exact"]
        calls = []
        def fake_call(argv, **kwargs):
            calls.append(argv[:])
            if argv[2] == "list":
                kwargs["stdout"].write(json.dumps(self.listing).encode())
                return 0
            self.assertEqual(argv, command)
            self.assertEqual(kwargs["env"]["NEXTEST_BIN_EXE_fixture_tool"], str(artifact))
            return 100
        with patch.object(ENV.subprocess, "call", side_effect=fake_call):
            self.assertEqual(ENV.run(command, self.metadata), 100)
        self.assertEqual(calls[-1], command)
        receipts = list(self.target.glob("hepta-nextest/*/receipt.json"))
        self.assertEqual(len(receipts), 1)
        receipt = json.loads(receipts[0].read_text())
        self.assertEqual(receipt["command_exit_code"], 100)
        self.assertEqual(receipt["status"], "ORIGINAL_COMMAND_TERMINAL_OBSERVATIONS_MATCH")

    def test_changed_helper_after_success_cannot_receive_successful_custody(self):
        artifact = self.add("fixture")
        command = ["cargo", "nextest", "run", "--no-fail-fast", "-p", "fixture"]
        def fake_call(argv, **kwargs):
            if argv[2] == "list":
                kwargs["stdout"].write(json.dumps(self.listing).encode())
            else:
                artifact.write_bytes(b"changed during command")
            return 0
        with patch.object(ENV.subprocess, "call", side_effect=fake_call):
            self.assertEqual(ENV.run(command, self.metadata), 1)
        receipt = json.loads(next(self.target.glob("hepta-nextest/*/receipt.json")).read_text())
        self.assertEqual(receipt["command_exit_code"], 0)
        self.assertEqual(receipt["status"], "BINARY_IDENTITY_REJECTED")
        self.assertIn("changed during", receipt["error"])

    def test_scoped_empty_helper_list_does_not_add_package_or_environment(self):
        command = ["cargo", "nextest", "run", "--no-fail-fast", "-p", "fixture", "--lib", "--locked"]
        calls = []
        def fake_call(argv, **kwargs):
            calls.append(argv[:])
            if argv[2] == "list":
                kwargs["stdout"].write(json.dumps(self.listing).encode())
            else:
                self.assertEqual(argv, command)
                self.assertNotIn("env", kwargs)
            return 0
        with patch.object(ENV.subprocess, "call", side_effect=fake_call):
            self.assertEqual(ENV.run(command, self.metadata), 0)
        self.assertNotIn("--workspace", calls[0])
        self.assertEqual(calls[0].count("-p"), 1)
        self.assertEqual(calls[-1], command)


if __name__ == "__main__":
    unittest.main()
