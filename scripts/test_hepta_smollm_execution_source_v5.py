"""Real Git source and reader controls, without a model or installation claim."""

import copy
import json
import subprocess
import unittest
from unittest.mock import patch

import hepta_neural_evidence_diverse_v3 as evidence
import hepta_neural_study_diverse_v3 as study
import hepta_smollm_execution_source_v1 as execution
import test_hepta_smollm_execution_source_v1 as original


class ExecutionSourceV5Tests(unittest.TestCase):
    def setUp(self):
        self.fixture = original.ExecutionSourceTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.historical = {
            p.name: p.read_bytes()
            for p in self.fixture.profiles.iterdir()
            if p.name != execution.MANIFEST_NAME_V5
        }
        self.fixture.source.write_bytes(b"fixture_source = 5\n")
        self.fixture.git("add", "scripts")
        self.fixture.commit()
        self.head = self.fixture.git("rev-parse", "HEAD").strip()
        self.tree = self.fixture.git("rev-parse", "HEAD^{tree}").strip()
        self.manifest = copy.deepcopy(self.fixture.manifest)
        self.manifest.update(
            schema="hepta-smollm-public-initial-execution-sources-v2",
            profile=execution.PROFILE_V5,
            chain_commit=self.head,
            chain_tree=self.tree,
        )
        self.manifest["files"]["scripts/controlled.py"] = {
            "size": self.fixture.source.stat().st_size,
            "sha256": execution.digest(self.fixture.source.read_bytes()),
        }
        self.path = self.fixture.profiles / execution.MANIFEST_NAME_V5
        self.enterContext(patch.object(execution, "CHAIN_COMMIT_V5", self.head))
        self.enterContext(patch.object(execution, "CHAIN_TREE_V5", self.tree))
        self.repin(self.manifest)

    def repin(self, value):
        self.path.write_text(json.dumps(value))
        self.enterContext(
            patch.object(
                execution,
                "MANIFEST_SHA256_V5",
                execution.digest(self.path.read_bytes()),
            )
        )

    def test_actual_commit_and_tree_are_bound_without_authority(self):
        actual = execution.verify(self.fixture.chain, execution.PROFILE_V5)
        self.assertEqual(
            (actual["chain_commit"], actual["chain_tree"]), (self.head, self.tree)
        )
        self.assertFalse(actual["model_compatibility_changed"])
        self.assertFalse(actual["product_qualification"])
        self.assertFalse(actual["installation_authorized"])
        self.assertEqual(
            {
                name: (self.fixture.profiles / name).read_bytes()
                for name in self.historical
            },
            self.historical,
        )

    def test_old_profiles_cannot_qualify_new_checkout(self):
        for profile in execution.registered_sources():
            if profile == execution.PROFILE_V5:
                continue
            with self.subTest(profile=profile):
                with self.assertRaisesRegex(
                    ValueError, "exact integrated Chain commit"
                ):
                    execution.verify(self.fixture.chain, profile)

    def test_relabelled_tree_is_rejected_even_with_rehashed_manifest(self):
        self.repin(dict(self.manifest, chain_tree="a" * 40))
        with self.assertRaisesRegex(ValueError, "exact integrated Chain tree"):
            execution.verify(self.fixture.chain, execution.PROFILE_V5)
        with patch.object(execution, "CHAIN_TREE_V5", "a" * 40):
            with self.assertRaisesRegex(ValueError, "exact integrated Chain tree"):
                execution.verify(self.fixture.chain, execution.PROFILE_V5)

    def test_missing_tree_and_legacy_schema_cannot_become_v5(self):
        for change in (
            {"schema": "hepta-smollm-public-initial-execution-sources-v1"},
            {"chain_tree": None},
        ):
            with self.subTest(change=change):
                self.repin(dict(self.manifest, **change))
                with self.assertRaises(ValueError):
                    execution.verify(self.fixture.chain, execution.PROFILE_V5)
        changed = dict(self.manifest)
        del changed["chain_tree"]
        self.repin(changed)
        with self.assertRaises(ValueError):
            execution.verify(self.fixture.chain, execution.PROFILE_V5)

    def test_all_consumers_select_one_source_before_any_chain_import(self):
        roles = dict(original.LEGACY_ROLES)
        roles["hepta_neural_study_diverse_v3"] = {
            "TRAINING_COMMIT": self.head,
            "TRAINING_TREE": self.tree,
        }
        pins = dict(
            self.fixture.fixture_pins(),
            CHAIN_COMMIT_V5=self.head,
            CHAIN_TREE_V5=self.tree,
            MANIFEST_SHA256_V5=execution.MANIFEST_SHA256_V5,
        )
        actual = self.fixture.import_consumers(roles, execution.PROFILE_V5, pins)
        self.assertEqual(actual.returncode, 0, actual.stderr)
        expected = {
            name: dict.fromkeys(fields, self.head)
            for name, fields in original.LEGACY_ROLES.items()
        }
        expected["hepta_neural_study_diverse_v3"] = roles[
            "hepta_neural_study_diverse_v3"
        ]
        self.assertEqual(json.loads(actual.stdout), expected)
        legacy = self.fixture.import_consumers(original.LEGACY_ROLES, None)
        self.assertEqual(legacy.returncode, 0, legacy.stderr)
        self.assertEqual(json.loads(legacy.stdout), original.LEGACY_ROLES)

    def test_manifest_tamper_is_refused_by_every_selected_consumer(self):
        self.path.write_bytes(self.path.read_bytes() + b" ")
        pins = dict(
            self.fixture.fixture_pins(),
            CHAIN_COMMIT_V5=self.head,
            CHAIN_TREE_V5=self.tree,
            MANIFEST_SHA256_V5=execution.MANIFEST_SHA256_V5,
        )
        for name, fields in original.LEGACY_ROLES.items():
            with self.subTest(consumer=name):
                actual = self.fixture.import_consumers(
                    {name: fields}, execution.PROFILE_V5, pins
                )
                self.assertNotEqual(actual.returncode, 0)
                self.assertIn("exact execution-source manifest", actual.stderr)

    def test_diverse_training_rejects_dirty_source_before_original_checkout(self):
        self.fixture.source.write_bytes(b"unreviewed = True\n")
        with (
            patch.object(
                study.original, "EXECUTION_SOURCE_PROFILE", execution.PROFILE_V5
            ),
            patch.object(study.original, "checkout") as checkout,
        ):
            with self.assertRaises(subprocess.CalledProcessError):
                study.checkout_training_tree(self.fixture.chain)
            checkout.assert_not_called()

    def test_reader_rejects_every_mixed_execution_role(self):
        repositories = {
            name: {"identity": {"commit": self.head, "tree": self.tree}}
            for name in evidence.REPOSITORIES
        }
        with patch.object(
            study.original, "EXECUTION_SOURCE_PROFILE", execution.PROFILE_V5
        ):
            observed = evidence.integrated_sources(repositories)
            self.assertEqual(observed["chain_commit"], self.head)
            for name in evidence.REPOSITORIES - {"hepta"}:
                for field in ("commit", "tree"):
                    with self.subTest(role=name, field=field):
                        changed = copy.deepcopy(repositories)
                        changed[name]["identity"][field] = "b" * 40
                        with self.assertRaisesRegex(ValueError, "same V5 Chain"):
                            evidence.integrated_sources(changed)
        self.assertIsNone(evidence.integrated_sources(repositories))

    def test_unfrozen_source_cannot_import_diverse_training(self):
        pins = dict(
            self.fixture.fixture_pins(),
            CHAIN_COMMIT_V5="UNPUBLISHED",
            CHAIN_TREE_V5=self.tree,
            MANIFEST_SHA256_V5=execution.MANIFEST_SHA256_V5,
        )
        result = self.fixture.import_consumers(
            {"hepta_neural_study_diverse_v3": {"TRAINING_COMMIT": self.head}},
            execution.PROFILE_V5,
            pins,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not been frozen", result.stderr)


if __name__ == "__main__":
    unittest.main()
