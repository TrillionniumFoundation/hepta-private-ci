"""V12 source controls use Git fixtures, never model or runtime qualification."""

import copy
import importlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import hepta_smollm_execution_source_v1 as execution
import test_hepta_smollm_execution_source_v11 as runtime_fixtures
import hepta_smollm_runtime_handoff_v12 as handoff


class CooperativeStopExecutionSourceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = runtime_fixtures.RuntimeBoundExecutionSourceTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.chain = self.fixture.chain
        self.historical = {
            path.name: path.read_bytes()
            for path in self.fixture.fixture.profiles.iterdir()
            if path.name != execution.MANIFEST_NAME_V12
        }
        files = copy.deepcopy(self.fixture.manifest["files"])
        # These bytes are deliberately non-executable source fixtures. Only the
        # separately executed Chain controls may establish cancellation behavior.
        for relative in (
            "scripts/llm_runtime_pilot.py",
            "scripts/llm_neural_read_worker.py",
        ):
            path = self.chain / relative
            raw = path.read_bytes() + b"new cancellation-source identity fixture\n"
            path.write_bytes(raw)
            files[relative] = dict(size=len(raw), sha256=execution.digest(raw))
        self.fixture.fixture.git("add", "scripts")
        self.fixture.fixture.commit()
        self.head = self.fixture.fixture.git("rev-parse", "HEAD").strip()
        self.tree = self.fixture.fixture.git("rev-parse", "HEAD^{tree}").strip()
        self.manifest = dict(
            self.fixture.manifest,
            profile=execution.PROFILE_V12,
            chain_commit=self.head,
            chain_tree=self.tree,
            files=files,
        )
        self.path = self.fixture.fixture.profiles / execution.MANIFEST_NAME_V12
        self.enterContext(patch.object(execution, "CHAIN_COMMIT_V12", self.head))
        self.enterContext(patch.object(execution, "CHAIN_TREE_V12", self.tree))
        self.repin(self.manifest)

    def repin(self, manifest):
        self.path.write_text(json.dumps(manifest))
        self.enterContext(
            patch.object(
                execution,
                "MANIFEST_SHA256_V12",
                execution.digest(self.path.read_bytes()),
            )
        )

    def verify(self):
        return execution.verify(self.chain, execution.PROFILE_V12)

    def test_new_identity_preserves_v11_and_cannot_issue_runtime_authority(self):
        result = self.verify()
        self.assertEqual(
            result,
            {
                "schema": "hepta-smollm-public-initial-execution-source-verified-v1",
                "profile": execution.PROFILE_V12,
                "chain_commit": self.head,
                "chain_tree": self.tree,
                "manifest_sha256": execution.digest(self.path.read_bytes()),
                "historical_profile_sha256": self.manifest["historical_profile_sha256"],
                "historical_sources_sha256": self.manifest["historical_sources_sha256"],
                "verified_source_files": len(self.manifest["files"]),
                "model_compatibility_changed": False,
                "product_qualification": False,
                "installation_authorized": False,
            },
        )
        self.assertEqual(
            self.historical,
            {
                path.name: path.read_bytes()
                for path in self.fixture.fixture.profiles.iterdir()
                if path.name != execution.MANIFEST_NAME_V12
            },
        )
        self.assertEqual(execution.checked_manifest(execution.PROFILE_V11), self.fixture.manifest)
        with self.assertRaisesRegex(ValueError, "exact integrated Chain commit"):
            execution.verify(self.chain, execution.PROFILE_V11)

    def test_unfrozen_commit_manifest_or_tree_refuses_before_git(self):
        for field, message in (
            ("CHAIN_COMMIT_V12", "not been frozen"),
            ("MANIFEST_SHA256_V12", "not been frozen"),
            ("CHAIN_TREE_V12", "exact integrated Chain tree"),
        ):
            with self.subTest(field=field), patch.object(execution, field, "UNFROZEN"), \
                 patch.object(execution, "git", side_effect=AssertionError("no checkout")) as git:
                with self.assertRaisesRegex(ValueError, message):
                    self.verify()
                git.assert_not_called()

    def test_relabelled_v11_manifest_refuses_even_when_rehashed(self):
        self.repin(dict(self.fixture.manifest, profile=execution.PROFILE_V12))
        with self.assertRaisesRegex(ValueError, "closed exact execution-source identity"):
            self.verify()

    def test_new_commit_with_old_worker_pins_refuses(self):
        changed = copy.deepcopy(self.manifest)
        changed["files"] = copy.deepcopy(self.fixture.manifest["files"])
        self.repin(changed)
        with self.assertRaisesRegex(ValueError, "execution source (size or path|bytes) changed"):
            self.verify()

    def test_runtime_admission_and_complete_v11_closure_cannot_be_omitted(self):
        for relative in (
            "scripts/llm_python_runtime_contract.py",
            "scripts/llm_runtime_pilot.py",
            "scripts/llm_neural_read_worker.py",
            "formal/pon-nakamoto-v1/contract_wire.py",
            "scripts/controlled.py",
        ):
            with self.subTest(relative=relative):
                changed = copy.deepcopy(self.manifest)
                del changed["files"][relative]
                self.repin(changed)
                with self.assertRaisesRegex(ValueError, "V12 requires the complete V11 and runtime"):
                    self.verify()

    def test_profile_cannot_declare_a_runtime_snapshot_bypass(self):
        for key in ("runtime_snapshot_optional", "legacy_worker_allowed"):
            with self.subTest(key=key):
                self.repin(dict(self.manifest, **{key: True}))
                with self.assertRaisesRegex(ValueError, "closed exact execution-source identity"):
                    self.verify()

    def test_old_forward_paths_refuse_v12_before_reading_inputs_or_importing_chain(self):
        forward = importlib.import_module("hepta_neural_forward_v1")
        study = importlib.import_module("hepta_neural_study_v1")
        with patch.object(execution, "verify_selected", side_effect=AssertionError("no Chain import")):
            with patch.object(forward, "EXECUTION_SOURCE_PROFILE", execution.PROFILE_V12):
                with self.assertRaisesRegex(ValueError, "V12.*legacy worker-v1"):
                    forward.run(SimpleNamespace())
            with patch.object(study, "EXECUTION_SOURCE_PROFILE", execution.PROFILE_V12):
                with self.assertRaisesRegex(ValueError, "V12.*legacy worker-v1"):
                    study.forward({}, None)
        execution.require_legacy_worker_profile(execution.PROFILE_V10)
        execution.require_legacy_worker_profile(None)

    def test_native_source_and_dependency_lock_remain_bound(self):
        for path in (self.fixture.native, self.fixture.lockfile):
            with self.subTest(path=path):
                original = path.read_bytes()
                path.write_bytes(original + b"different native input\n")
                try:
                    with self.assertRaisesRegex(ValueError, "candidate checkout is dirty"):
                        self.verify()
                finally:
                    path.write_bytes(original)

    def test_hidden_index_flags_and_ignored_import_inputs_refuse_without_repair(self):
        relative = "scripts/llm_runtime_pilot.py"
        for flag in ("assume-unchanged", "skip-worktree"):
            with self.subTest(flag=flag):
                self.fixture.fixture.git("update-index", "--" + flag, relative)
                before = self.fixture.fixture.git("ls-files", "-v", "--", relative)
                try:
                    with self.assertRaisesRegex(ValueError, "hidden index"):
                        self.verify()
                    self.assertEqual(
                        self.fixture.fixture.git("ls-files", "-v", "--", relative), before
                    )
                finally:
                    self.fixture.fixture.git("update-index", "--no-" + flag, relative)
        for relative in ("scripts/ambient-shadow.py", "trillionnium/.cargo/config.toml"):
            with self.subTest(relative=relative):
                path = self.chain / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("unapproved input\n")
                try:
                    with self.assertRaisesRegex(ValueError, "V12.*ignored inputs"):
                        self.verify()
                finally:
                    path.unlink()

    def test_inherited_no_bytecode_policy_is_still_required(self):
        with patch.dict(os.environ, {"PYTHONDONTWRITEBYTECODE": "0"}):
            with self.assertRaisesRegex(ValueError, "V12 requires disabled bytecode"):
                self.verify()

    def test_ordered_merge_uses_original_candidate_owner_and_rejects_reversed_parents(self):
        git = self.fixture.fixture.git
        base = self.fixture.head
        for parents in ((base, self.head), (self.head, base)):
            merged = git(
                "-c", "user.name=Controlled source fixture",
                "-c", "user.email=fixture@example.invalid",
                "commit-tree", self.tree, "-p", parents[0], "-p", parents[1],
                "-m", "controlled ordered merge fixture",
            ).strip()
            git("checkout", "--quiet", "--detach", merged)
            if parents[0] == base:
                result = execution.verify_merged(self.chain, execution.PROFILE_V12, base)
                self.assertEqual(
                    (result["tested_commit"], result["base_commit"], result["lane"]),
                    (merged, base, "base-merge"),
                )
            else:
                with self.assertRaisesRegex(ValueError, "prospective merge parents"):
                    execution.verify_merged(self.chain, execution.PROFILE_V12, base)

    def test_successor_commit_cannot_inherit_v12_source_evidence(self):
        (self.chain / "README.md").write_text("another source identity\n")
        self.fixture.fixture.git("add", "README.md")
        self.fixture.fixture.commit()
        with self.assertRaisesRegex(ValueError, "exact integrated Chain commit"):
            self.verify()


class OriginalHostHandoffTests(unittest.TestCase):
    def setUp(self):
        self.fixture = CooperativeStopExecutionSourceTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.chain = self.fixture.chain
        # This non-executed entry fixture tests source admission and exec wiring;
        # it cannot establish an actual model, snapshot or native owner result.
        entry = self.chain / handoff.ENTRY
        entry.write_text("raise RuntimeError('non-executed handoff source fixture')\n")
        git = self.fixture.fixture.fixture.git
        git("add", handoff.ENTRY)
        self.fixture.fixture.fixture.commit()
        manifest = copy.deepcopy(self.fixture.manifest)
        manifest.update(chain_commit=git("rev-parse", "HEAD").strip(),
                        chain_tree=git("rev-parse", "HEAD^{tree}").strip())
        manifest["files"][handoff.ENTRY] = dict(
            size=entry.stat().st_size, sha256=execution.digest(entry.read_bytes()))
        self.enterContext(patch.object(execution, "CHAIN_COMMIT_V12", manifest["chain_commit"]))
        self.enterContext(patch.object(execution, "CHAIN_TREE_V12", manifest["chain_tree"]))
        self.fixture.repin(manifest)
        self.values = {"--" + name: str(self.chain / ("fixture-" + name)) for name in handoff.PATHS}
        self.values.update({
            "--chain": str(self.chain), "--hepta": str(Path(handoff.__file__).resolve().parents[1]),
            "--python": sys.executable, "--consumer-mode": "cell-host-v2",
            "--handoff-config-sha256": "a" * 64, "--runtime-snapshot-sha256": "b" * 64,
            "--cache-max-bytes": "272189990", "--cache-max-chunks": "8192",
            "--cache-max-manifests": "64", "--cache-max-db-bytes": "536870912",
        })

    def arguments(self, values=None):
        return [item for pair in (values or self.values).items() for item in pair]

    def test_verified_source_execs_original_entry_with_unchanged_owner_snapshot_and_budgets(self):
        args = self.arguments()
        with patch.object(handoff.os, "execv", side_effect=SystemExit(19)) as execute:
            with self.assertRaises(SystemExit) as result:
                handoff.delegate(execution.PROFILE_V12, args)
        self.assertEqual(result.exception.code, 19)
        execute.assert_called_once_with(
            sys.executable, [sys.executable, "-B", str(self.chain / handoff.ENTRY), *args])

    def test_cli_requires_separator_and_delegates_the_same_complete_arguments(self):
        arguments = self.arguments()
        with patch.object(sys, "argv", ["handoff", "--profile", execution.PROFILE_V12, "--", *arguments]), \
             patch.object(handoff.os, "execv", side_effect=SystemExit(23)) as execute:
            with self.assertRaises(SystemExit) as result:
                handoff.main()
        self.assertEqual(result.exception.code, 23)
        execute.assert_called_once_with(
            sys.executable, [sys.executable, "-B", str(self.chain / handoff.ENTRY), *arguments])

    def test_legacy_source_or_consumer_is_rejected_before_any_delegation(self):
        values = dict(self.values, **{"--consumer-mode": "original-v1"})
        with patch.object(execution, "verify", side_effect=AssertionError("no source use")) as verify, \
             patch.object(handoff.os, "execv", side_effect=AssertionError("no delegation")) as execute:
            with self.assertRaisesRegex(ValueError, "explicit V12"):
                handoff.delegate(execution.PROFILE_V11, self.arguments())
            with self.assertRaisesRegex(ValueError, "original-v1"):
                handoff.delegate(execution.PROFILE_V12, self.arguments(values))
            verify.assert_not_called()
            execute.assert_not_called()

    def test_missing_snapshot_owner_pin_or_resource_flag_never_selects_defaults(self):
        for flag in ("--runtime-snapshot", "--runtime-snapshot-sha256", "--handoff-config",
                     "--handoff-config-sha256", "--cache-max-db-bytes"):
            with self.subTest(flag=flag), patch.object(handoff.os, "execv") as execute:
                values = dict(self.values)
                del values[flag]
                with self.assertRaisesRegex(ValueError, "complete original handoff arguments"):
                    handoff.delegate(execution.PROFILE_V12, self.arguments(values))
                execute.assert_not_called()

    def test_duplicate_or_extra_arguments_cannot_override_the_checked_snapshot(self):
        changed = self.arguments()
        index = changed.index("--handoff-config-sha256")
        changed[index] = "--runtime-snapshot-sha256"
        with patch.object(handoff.os, "execv") as execute:
            with self.assertRaisesRegex(ValueError, "closed unique handoff flags"):
                handoff.delegate(execution.PROFILE_V12, changed)
            with self.assertRaisesRegex(ValueError, "complete original handoff arguments"):
                handoff.delegate(execution.PROFILE_V12,
                                 self.arguments() + ["--consumer-mode", "original-v1"])
            execute.assert_not_called()

    def test_unfrozen_or_dirty_source_refuses_without_an_exec(self):
        with patch.object(handoff.os, "execv") as execute:
            with patch.object(execution, "CHAIN_COMMIT_V12", "UNFROZEN"):
                with self.assertRaisesRegex(ValueError, "not been frozen"):
                    handoff.delegate(execution.PROFILE_V12, self.arguments())
            source = self.chain / "scripts/llm_runtime_pilot.py"
            source.write_bytes(source.read_bytes() + b"unreviewed cancellation code\n")
            with self.assertRaisesRegex(ValueError, "candidate checkout is dirty"):
                handoff.delegate(execution.PROFILE_V12, self.arguments())
            execute.assert_not_called()

    def test_inexact_runtime_pin_or_mixed_hepta_checkout_cannot_delegate(self):
        for flag, value, message in (
            ("--runtime-snapshot-sha256", "unfrozen", "exact original input pin"),
            ("--runtime-snapshot", "relative-runtime.json", "absolute original"),
            ("--hepta", str(self.chain), "retain this Hepta source"),
        ):
            with self.subTest(flag=flag), patch.object(handoff.os, "execv") as execute:
                values = dict(self.values, **{flag: value})
                with self.assertRaisesRegex(ValueError, message):
                    handoff.delegate(execution.PROFILE_V12, self.arguments(values))
                execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
