"""Ordinary source binding covers native inputs as well as Python imports."""

import json
import unittest
from unittest.mock import patch

import hepta_neural_evidence_diverse_v3 as evidence
import hepta_smollm_execution_source_v1 as execution
import test_hepta_smollm_execution_source_v1 as original


class ExecutionSourceV10Tests(unittest.TestCase):
    def setUp(self):
        self.fixture = original.ExecutionSourceTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.chain = self.fixture.chain
        self.native = self.chain / "trillionnium/crates/native/src/lib.rs"
        self.native.parent.mkdir(parents=True)
        self.native.write_text("pub const VALUE: u64 = 1;\n")
        self.lockfile = self.chain / "trillionnium/Cargo.lock"
        self.lockfile.write_text("version = 4\n")
        (self.chain / ".gitignore").write_text(
            "**/ambient-*\n**/.cargo/config\n**/.cargo/config.toml\n"
        )
        self.fixture.git("add", ".")
        self.fixture.commit()
        self.head = self.fixture.git("rev-parse", "HEAD").strip()
        self.tree = self.fixture.git("rev-parse", "HEAD^{tree}").strip()
        for version in ("V9", "V10"):
            profile = getattr(execution, "PROFILE_" + version)
            manifest = dict(
                execution.checked_manifest(profile),
                chain_commit=self.head,
                chain_tree=self.tree,
            )
            path = self.fixture.profiles / getattr(
                execution, "MANIFEST_NAME_" + version
            )
            path.write_text(json.dumps(manifest))
            for name, value in (
                ("CHAIN_COMMIT_" + version, self.head),
                ("CHAIN_TREE_" + version, self.tree),
                ("MANIFEST_SHA256_" + version, execution.digest(path.read_bytes())),
            ):
                self.enterContext(patch.object(execution, name, value))

    def test_native_raw_bytes_and_lockfile_drift_refuse_ordinary_source(self):
        for path in (self.native, self.lockfile):
            with self.subTest(path=path.relative_to(self.chain)):
                original_bytes = path.read_bytes()
                path.write_bytes(original_bytes + b"# source changed\n")
                try:
                    # The historical Python-only guard still has its original
                    # meaning; its acceptance cannot qualify the new native pair.
                    execution.verify(self.chain, execution.PROFILE_V9)
                    with self.assertRaisesRegex(
                        ValueError, "candidate checkout is dirty"
                    ):
                        execution.verify(self.chain, execution.PROFILE_V10)
                finally:
                    path.write_bytes(original_bytes)

    def test_native_hidden_index_entries_refuse_without_clearing_flags(self):
        relative = str(self.native.relative_to(self.chain))
        for flag in ("assume-unchanged", "skip-worktree"):
            with self.subTest(flag=flag):
                self.fixture.git("update-index", "--" + flag, relative)
                before = self.fixture.git("ls-files", "-v", "--", relative)
                try:
                    execution.verify(self.chain, execution.PROFILE_V9)
                    with self.assertRaisesRegex(ValueError, "hidden index"):
                        execution.verify(self.chain, execution.PROFILE_V10)
                    self.assertEqual(
                        self.fixture.git("ls-files", "-v", "--", relative), before
                    )
                finally:
                    self.fixture.git("update-index", "--no-" + flag, relative)

    def test_ignored_native_inputs_and_cargo_configuration_refuse(self):
        for relative in (
            "trillionnium/crates/native/src/ambient-module.rs",
            "trillionnium/.cargo/config.toml",
            ".cargo/config.toml",
            ".cargo/config",
        ):
            with self.subTest(path=relative):
                path = self.chain / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("unreviewed input\n")
                try:
                    execution.verify(self.chain, execution.PROFILE_V9)
                    with self.assertRaisesRegex(ValueError, "V10.*ignored inputs"):
                        execution.verify(self.chain, execution.PROFILE_V10)
                finally:
                    path.unlink()

    def test_clean_source_binds_all_ordinary_roles_without_granting_authority(self):
        before = {p.name: p.read_bytes() for p in self.fixture.profiles.iterdir()}
        result = execution.verify(self.chain, execution.PROFILE_V10)
        self.assertEqual(
            (result["chain_commit"], result["chain_tree"]), (self.head, self.tree)
        )
        self.assertEqual(
            [
                result[k]
                for k in (
                    "model_compatibility_changed",
                    "product_qualification",
                    "installation_authorized",
                )
            ],
            [False, False, False],
        )
        roles = dict(original.LEGACY_ROLES)
        roles["hepta_neural_study_diverse_v3"] = {
            "TRAINING_COMMIT": self.head,
            "TRAINING_TREE": self.tree,
        }
        pins = dict(
            self.fixture.fixture_pins(),
            CHAIN_COMMIT_V10=self.head,
            CHAIN_TREE_V10=self.tree,
            MANIFEST_SHA256_V10=execution.MANIFEST_SHA256_V10,
        )
        actual = self.fixture.import_consumers(roles, execution.PROFILE_V10, pins)
        self.assertEqual(actual.returncode, 0, actual.stderr)
        expected = {
            name: dict.fromkeys(fields, self.head)
            for name, fields in original.LEGACY_ROLES.items()
        }
        expected["hepta_neural_study_diverse_v3"] = roles[
            "hepta_neural_study_diverse_v3"
        ]
        self.assertEqual(json.loads(actual.stdout), expected)
        self.assertEqual(
            {p.name: p.read_bytes() for p in self.fixture.profiles.iterdir()}, before
        )

    def test_mixed_execution_roles_and_successor_metadata_need_fresh_evidence(self):
        repositories = {
            name: {"identity": {"commit": self.head, "tree": self.tree}}
            for name in evidence.REPOSITORIES
        }
        for name in evidence.REPOSITORIES - {"hepta"}:
            with self.subTest(role=name):
                repositories[name]["identity"]["commit"] = "f" * 40
                with (
                    patch.object(
                        evidence.study_driver.original,
                        "EXECUTION_SOURCE_PROFILE",
                        execution.PROFILE_V10,
                    ),
                    self.assertRaisesRegex(ValueError, "same V10 Chain"),
                ):
                    evidence.integrated_sources(repositories)
                repositories[name]["identity"]["commit"] = self.head
        (self.chain / "README.md").write_text("new source identity\n")
        self.fixture.git("add", "README.md")
        self.fixture.commit()
        with self.assertRaisesRegex(ValueError, "exact integrated Chain commit"):
            execution.verify(self.chain, execution.PROFILE_V10)


if __name__ == "__main__":
    unittest.main()
