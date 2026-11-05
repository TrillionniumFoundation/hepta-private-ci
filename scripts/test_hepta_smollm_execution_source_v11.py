"""Independent V11 source controls; no model or previous-profile qualification."""

import copy
import importlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import hepta_smollm_execution_source_v1 as execution
import test_hepta_smollm_execution_source_v1 as fixtures


class RuntimeBoundExecutionSourceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ExecutionSourceTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.chain = self.fixture.chain
        self.historical = {
            path.name: path.read_bytes()
            for path in self.fixture.profiles.iterdir()
            if path.name != execution.MANIFEST_NAME_V11
        }
        files = copy.deepcopy(self.fixture.manifest["files"])
        for relative in execution.RUNTIME_SOURCES_V11:
            path = self.chain / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            raw = ("explicit non-executed source fixture: " + relative + "\n").encode()
            path.write_bytes(raw)
            files[relative] = dict(size=len(raw), sha256=execution.digest(raw))
        self.native = self.chain / "trillionnium/crates/native/src/lib.rs"
        self.native.parent.mkdir(parents=True)
        self.native.write_text("pub const UNUSED_SOURCE_FIXTURE: u64 = 1;\n")
        self.lockfile = self.chain / "trillionnium/Cargo.lock"
        self.lockfile.write_text("version = 4\n")
        (self.chain / ".gitignore").write_text("**/ambient-*\n**/.cargo/config.toml\n")
        self.fixture.git("add", ".")
        self.fixture.commit()
        self.head = self.fixture.git("rev-parse", "HEAD").strip()
        self.tree = self.fixture.git("rev-parse", "HEAD^{tree}").strip()
        self.manifest = dict(
            self.fixture.manifest,
            schema="hepta-smollm-public-initial-execution-sources-v2",
            profile=execution.PROFILE_V11,
            chain_commit=self.head,
            chain_tree=self.tree,
            files=files,
        )
        self.path = self.fixture.profiles / execution.MANIFEST_NAME_V11
        self.enterContext(patch.object(execution, "CHAIN_COMMIT_V11", self.head))
        self.enterContext(patch.object(execution, "CHAIN_TREE_V11", self.tree))
        self.repin(self.manifest)

    def repin(self, value):
        self.path.write_text(json.dumps(value))
        self.enterContext(
            patch.object(
                execution,
                "MANIFEST_SHA256_V11",
                execution.digest(self.path.read_bytes()),
            )
        )

    def verify(self):
        return execution.verify(self.chain, execution.PROFILE_V11)

    def test_new_source_binds_runtime_closure_and_keeps_all_historical_records(self):
        result = self.verify()
        self.assertEqual(
            (result["chain_commit"], result["chain_tree"]), (self.head, self.tree)
        )
        self.assertEqual(result["verified_source_files"], len(self.manifest["files"]))
        self.assertEqual(
            [
                result[name]
                for name in (
                    "model_compatibility_changed",
                    "product_qualification",
                    "installation_authorized",
                )
            ],
            [False, False, False],
        )
        self.assertEqual(
            self.historical,
            {
                path.name: path.read_bytes()
                for path in self.fixture.profiles.iterdir()
                if path.name != execution.MANIFEST_NAME_V11
            },
        )

    def test_omitted_helper_base_transitive_config_or_v10_source_refuses_even_when_rehashed(
        self,
    ):
        for relative in (
            "scripts/llm_python_runtime_contract.py",
            "scripts/llm_base_material.py",
            "formal/pon-nakamoto-v1/contract_wire.py",
            "config/pon/devnet-v1.json",
            "scripts/controlled.py",
        ):
            with self.subTest(relative=relative):
                changed = copy.deepcopy(self.manifest)
                del changed["files"][relative]
                self.repin(changed)
                with self.assertRaisesRegex(
                    ValueError, "V11 requires the complete V10 and runtime"
                ):
                    self.verify()
        self.repin(self.manifest)

    def test_actual_helper_byte_drift_refuses_without_changing_source_identity(self):
        path = self.chain / "scripts/llm_python_runtime_contract.py"
        path.write_bytes(
            path.read_bytes() + b"different source with the same public version\n"
        )
        with self.assertRaisesRegex(ValueError, "candidate checkout is dirty"):
            self.verify()

    def test_hidden_runtime_index_flags_refuse_without_repair(self):
        relative = "scripts/llm_python_runtime_contract.py"
        for flag in ("assume-unchanged", "skip-worktree"):
            with self.subTest(flag=flag):
                self.fixture.git("update-index", "--" + flag, relative)
                before = self.fixture.git("ls-files", "-v", "--", relative)
                try:
                    with self.assertRaisesRegex(ValueError, "hidden index"):
                        self.verify()
                    self.assertEqual(
                        self.fixture.git("ls-files", "-v", "--", relative), before
                    )
                finally:
                    self.fixture.git("update-index", "--no-" + flag, relative)

    def test_ignored_import_and_native_configuration_inputs_refuse(self):
        for relative in (
            "scripts/ambient-shadow.py",
            "trillionnium/.cargo/config.toml",
            ".cargo/config.toml",
        ):
            with self.subTest(relative=relative):
                path = self.chain / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("unapproved input\n")
                try:
                    with self.assertRaisesRegex(ValueError, "V11.*ignored inputs"):
                        self.verify()
                finally:
                    path.unlink()

    def test_native_source_and_lockfile_drift_remain_inside_the_new_profile(self):
        for path in (self.native, self.lockfile):
            with self.subTest(path=path):
                original = path.read_bytes()
                path.write_bytes(original + b"changed native input\n")
                try:
                    with self.assertRaisesRegex(
                        ValueError, "candidate checkout is dirty"
                    ):
                        self.verify()
                finally:
                    path.write_bytes(original)

    def test_unfrozen_or_successor_identity_cannot_inherit_the_profile(self):
        with patch.object(execution, "CHAIN_COMMIT_V11", "UNFROZEN_PENDING_SOURCE"):
            with self.assertRaisesRegex(ValueError, "not been frozen"):
                self.verify()
        (self.chain / "README.md").write_text("new source identity\n")
        self.fixture.git("add", "README.md")
        self.fixture.commit()
        with self.assertRaisesRegex(ValueError, "exact integrated Chain commit"):
            self.verify()

    def test_old_worker_forward_cannot_consume_the_runtime_bound_source_profile(self):
        forward = importlib.import_module("hepta_neural_forward_v1")
        study = importlib.import_module("hepta_neural_study_v1")
        with patch.object(forward, "EXECUTION_SOURCE_PROFILE", execution.PROFILE_V11):
            with self.assertRaisesRegex(ValueError, "legacy worker-v1"):
                forward.run(SimpleNamespace())
        with patch.object(study, "EXECUTION_SOURCE_PROFILE", execution.PROFILE_V11):
            with self.assertRaisesRegex(ValueError, "legacy worker-v1"):
                study.forward({}, None)
        execution.require_legacy_worker_profile(execution.PROFILE_V10)
        execution.require_legacy_worker_profile(None)

    def test_inherited_bytecode_policy_cannot_be_removed_for_the_new_source(self):
        with patch.dict(os.environ, {"PYTHONDONTWRITEBYTECODE": "0"}):
            with self.assertRaisesRegex(ValueError, "V11 requires disabled bytecode"):
                self.verify()


if __name__ == "__main__":
    unittest.main()
