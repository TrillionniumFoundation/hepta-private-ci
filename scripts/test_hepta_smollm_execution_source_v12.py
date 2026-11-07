"""Exact-current-source controls using a tiny Git fixture, never model qualification."""

import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import hepta_smollm_execution_source_v1 as execution


class CurrentExecutionSourceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name).resolve()
        self.chain, self.profiles = root / "chain", root / "profiles"
        self.chain.mkdir()
        self.profiles.mkdir()
        self.git("init", "--quiet")
        initial = self.chain / "README.md"
        initial.write_text("source fixture; no workload execution\n")
        self.git("add", ".")
        self.commit()
        self.base = self.git("rev-parse", "HEAD")
        files = {}
        for relative in sorted(
            execution.RUNTIME_SOURCES_V11 | {"scripts/controlled.py"}
        ):
            path = self.chain / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            raw = ("controlled nonexecuted source " + relative + "\n").encode()
            path.write_bytes(raw)
            files[relative] = {"size": len(raw), "sha256": execution.digest(raw)}
        self.native = self.chain / "trillionnium/crates/fixture/src/lib.rs"
        self.native.parent.mkdir(parents=True)
        self.native.write_text("pub const SOURCE_FIXTURE: u64 = 1;\n")
        self.lockfile = self.chain / "trillionnium/Cargo.lock"
        self.lockfile.write_text("version = 4\n")
        (self.chain / ".gitignore").write_text("**/ambient-*\n**/.cargo/config.toml\n")
        self.git("add", ".")
        self.commit()
        self.head = self.git("rev-parse", "HEAD")
        self.tree = self.git("rev-parse", "HEAD^{tree}")
        self.profile = self.profiles / "smollm2-public-initial-v2.profile"
        self.profile.write_text("historical immutable compatibility fixture\n")
        self.original_sources = self.profiles / "smollm2-public-initial-v2.sources.json"
        self.original_sources.write_text(
            json.dumps({"files": {"scripts/controlled.py": {}}})
        )
        self.manifest = {
            "schema": "hepta-smollm-public-initial-execution-sources-v2",
            "profile": execution.PROFILE_V12,
            "chain_commit": self.head,
            "chain_tree": self.tree,
            "historical_profile_sha256": execution.digest(self.profile.read_bytes()),
            "historical_sources_sha256": execution.digest(
                self.original_sources.read_bytes()
            ),
            "files": files,
        }
        self.path = self.profiles / execution.MANIFEST_NAME_V12
        previous = self.profiles / execution.MANIFEST_NAME_V11
        previous.write_text(
            json.dumps(dict(self.manifest, profile=execution.PROFILE_V11))
        )
        for name, value in (
            ("PROFILES", self.profiles),
            ("CHAIN_COMMIT_V12", self.head),
            ("CHAIN_TREE_V12", self.tree),
            ("CHAIN_COMMIT_V11", self.head),
            ("CHAIN_TREE_V11", self.tree),
            ("MANIFEST_SHA256_V11", execution.digest(previous.read_bytes())),
            ("HISTORICAL_PROFILE_SHA256", self.manifest["historical_profile_sha256"]),
            ("HISTORICAL_SOURCES_SHA256", self.manifest["historical_sources_sha256"]),
        ):
            self.enterContext(patch.object(execution, name, value))
        self.historical = {
            path.name: path.read_bytes() for path in self.profiles.iterdir()
        }
        self.repin(self.manifest)

    def git(self, *args):
        return subprocess.check_output(
            [
                "git",
                "-C",
                str(self.chain),
                "-c",
                "user.name=Controlled source fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "-c",
                "commit.gpgsign=false",
                *args,
            ],
            text=True,
            stderr=subprocess.PIPE,
        ).strip()

    def commit(self):
        self.git("commit", "--quiet", "-m", "controlled source fixture")

    def repin(self, value):
        self.path.write_text(json.dumps(value))
        self.enterContext(
            patch.object(
                execution,
                "MANIFEST_SHA256_V12",
                execution.digest(self.path.read_bytes()),
            )
        )

    def verify(self):
        return execution.verify(self.chain, execution.PROFILE_V12)

    def test_exact_current_source_retains_history_and_grants_no_model_authority(self):
        value = self.verify()
        self.assertEqual(
            (value["chain_commit"], value["chain_tree"]), (self.head, self.tree)
        )
        self.assertEqual(value["verified_source_files"], len(self.manifest["files"]))
        for key in (
            "model_compatibility_changed",
            "product_qualification",
            "installation_authorized",
        ):
            self.assertIs(value[key], False)
        self.assertEqual(
            self.historical,
            {
                path.name: path.read_bytes()
                for path in self.profiles.iterdir()
                if path.name != execution.MANIFEST_NAME_V12
            },
        )

    def test_omitted_previous_or_runtime_source_refuses_even_with_rehashed_manifest(
        self,
    ):
        for relative in (
            "scripts/controlled.py",
            "scripts/llm_base_material.py",
            "scripts/llm_python_runtime_contract.py",
            "config/pon/devnet-v1.json",
        ):
            with self.subTest(relative=relative):
                changed = copy.deepcopy(self.manifest)
                del changed["files"][relative]
                self.repin(changed)
                with self.assertRaisesRegex(
                    ValueError, "V12 requires the complete V11 and runtime"
                ):
                    self.verify()

    def test_unfrozen_relabelled_unknown_and_successor_sources_refuse(self):
        with patch.object(execution, "CHAIN_COMMIT_V12", "UNFROZEN_PENDING_SOURCE"):
            with self.assertRaisesRegex(ValueError, "not been frozen"):
                self.verify()
        with self.assertRaisesRegex(ValueError, "closed execution-source profile"):
            execution.verify(self.chain, "arbitrary-current-source")
        changed = dict(self.manifest, chain_commit="a" * 40)
        self.repin(changed)
        with self.assertRaisesRegex(ValueError, "exact execution-source identity"):
            self.verify()
        self.repin(self.manifest)
        (self.chain / "README.md").write_text("successor source\n")
        self.git("add", ".")
        self.commit()
        with self.assertRaisesRegex(ValueError, "exact integrated Chain commit"):
            self.verify()

    def test_actual_native_lockfile_and_runtime_bytes_cannot_hide_behind_git_identity(
        self,
    ):
        for path in (
            self.native,
            self.lockfile,
            self.chain / "scripts/llm_python_runtime_contract.py",
        ):
            with self.subTest(path=path):
                original = path.read_bytes()
                path.write_bytes(original + b"changed actual source\n")
                try:
                    with self.assertRaisesRegex(
                        ValueError, "candidate checkout is dirty"
                    ):
                        self.verify()
                finally:
                    path.write_bytes(original)

    def test_hidden_index_flags_and_ignored_import_inputs_refuse_without_repair(self):
        relative = "scripts/llm_python_runtime_contract.py"
        for flag in ("assume-unchanged", "skip-worktree"):
            self.git("update-index", "--" + flag, relative)
            before = self.git("ls-files", "-v", "--", relative)
            try:
                with self.assertRaisesRegex(ValueError, "hidden index"):
                    self.verify()
                self.assertEqual(self.git("ls-files", "-v", "--", relative), before)
            finally:
                self.git("update-index", "--no-" + flag, relative)
        for relative in (
            "scripts/ambient-shadow.py",
            "trillionnium/.cargo/config.toml",
            ".cargo/config.toml",
        ):
            path = self.chain / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("unapproved ignored source input\n")
            try:
                with self.assertRaisesRegex(ValueError, "V12.*ignored inputs"):
                    self.verify()
            finally:
                path.unlink()

    def test_exact_ordered_merge_with_canonical_tree_is_source_evidence_only(self):
        merge = self.git(
            "commit-tree",
            self.tree,
            "-p",
            self.base,
            "-p",
            self.head,
            "-m",
            "ordered merge fixture",
        )
        self.git("checkout", "--quiet", "--detach", merge)
        value = execution.verify_merged(self.chain, execution.PROFILE_V12, self.base)
        self.assertEqual(value["chain_commit"], self.head)
        self.assertIs(value["product_qualification"], False)

    def test_identical_tree_with_reversed_merge_parents_is_rejected(self):
        merge = self.git(
            "commit-tree",
            self.tree,
            "-p",
            self.head,
            "-p",
            self.base,
            "-m",
            "reversed merge fixture",
        )
        self.git("checkout", "--quiet", "--detach", merge)
        with self.assertRaisesRegex(ValueError, "merge parents differ"):
            execution.verify_merged(self.chain, execution.PROFILE_V12, self.base)

    def test_legacy_worker_refusal_and_original_profiles_are_preserved(self):
        for profile in (execution.PROFILE_V11, execution.PROFILE_V12):
            with self.assertRaisesRegex(ValueError, "legacy worker-v1"):
                execution.require_legacy_worker_profile(profile)
        execution.require_legacy_worker_profile(execution.PROFILE_V10)
        execution.require_legacy_worker_profile(None)

    def test_inherited_bytecode_policy_remains_mandatory(self):
        with patch.dict(os.environ, {"PYTHONDONTWRITEBYTECODE": "0"}):
            with self.assertRaisesRegex(ValueError, "V12 requires disabled bytecode"):
                self.verify()


if __name__ == "__main__":
    unittest.main()
