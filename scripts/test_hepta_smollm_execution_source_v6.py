"""Real Git source and reader controls, without a model or installation claim."""

import copy
import json
import os
import subprocess
import unittest
from unittest.mock import patch

import hepta_neural_evidence_diverse_v3 as evidence
import hepta_neural_study_diverse_v3 as study
import hepta_smollm_execution_source_v1 as execution
import test_hepta_smollm_execution_source_v1 as original


class ExecutionSourceV6Tests(unittest.TestCase):
    def setUp(self):
        self.fixture = original.ExecutionSourceTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.historical = {
            p.name: p.read_bytes()
            for p in self.fixture.profiles.iterdir()
            if p.name != execution.MANIFEST_NAME_V6
        }
        self.fixture.source.write_bytes(b"fixture_source = 6\n")
        self.fixture.git("add", "scripts")
        self.fixture.commit()
        self.head = self.fixture.git("rev-parse", "HEAD").strip()
        self.tree = self.fixture.git("rev-parse", "HEAD^{tree}").strip()
        self.manifest = copy.deepcopy(self.fixture.manifest)
        self.manifest.update(
            schema="hepta-smollm-public-initial-execution-sources-v2",
            profile=execution.PROFILE_V6,
            chain_commit=self.head,
            chain_tree=self.tree,
        )
        self.manifest["files"]["scripts/controlled.py"] = {
            "size": self.fixture.source.stat().st_size,
            "sha256": execution.digest(self.fixture.source.read_bytes()),
        }
        self.path = self.fixture.profiles / execution.MANIFEST_NAME_V6
        self.enterContext(patch.object(execution, "CHAIN_COMMIT_V6", self.head))
        self.enterContext(patch.object(execution, "CHAIN_TREE_V6", self.tree))
        self.repin(self.manifest)

    def repin(self, value):
        self.path.write_text(json.dumps(value))
        self.enterContext(
            patch.object(
                execution,
                "MANIFEST_SHA256_V6",
                execution.digest(self.path.read_bytes()),
            )
        )

    def test_actual_commit_and_tree_are_bound_without_authority(self):
        actual = execution.verify(self.fixture.chain, execution.PROFILE_V6)
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
            if profile == execution.PROFILE_V6:
                continue
            with self.subTest(profile=profile):
                with self.assertRaisesRegex(
                    ValueError, "exact integrated Chain commit"
                ):
                    execution.verify(self.fixture.chain, profile)

    def test_relabelled_tree_is_rejected_even_with_rehashed_manifest(self):
        self.repin(dict(self.manifest, chain_tree="a" * 40))
        with self.assertRaisesRegex(ValueError, "exact integrated Chain tree"):
            execution.verify(self.fixture.chain, execution.PROFILE_V6)
        with patch.object(execution, "CHAIN_TREE_V6", "a" * 40):
            with self.assertRaisesRegex(ValueError, "exact integrated Chain tree"):
                execution.verify(self.fixture.chain, execution.PROFILE_V6)

    def test_missing_tree_and_legacy_schema_cannot_become_v6(self):
        for change in (
            {"schema": "hepta-smollm-public-initial-execution-sources-v1"},
            {"chain_tree": None},
        ):
            with self.subTest(change=change):
                self.repin(dict(self.manifest, **change))
                with self.assertRaises(ValueError):
                    execution.verify(self.fixture.chain, execution.PROFILE_V6)
        changed = dict(self.manifest)
        del changed["chain_tree"]
        self.repin(changed)
        with self.assertRaises(ValueError):
            execution.verify(self.fixture.chain, execution.PROFILE_V6)

    def test_all_consumers_select_one_source_before_any_chain_import(self):
        roles = dict(original.LEGACY_ROLES)
        roles["hepta_neural_study_diverse_v3"] = {
            "TRAINING_COMMIT": self.head,
            "TRAINING_TREE": self.tree,
        }
        pins = dict(
            self.fixture.fixture_pins(),
            CHAIN_COMMIT_V6=self.head,
            CHAIN_TREE_V6=self.tree,
            MANIFEST_SHA256_V6=execution.MANIFEST_SHA256_V6,
        )
        actual = self.fixture.import_consumers(roles, execution.PROFILE_V6, pins)
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
            CHAIN_COMMIT_V6=self.head,
            CHAIN_TREE_V6=self.tree,
            MANIFEST_SHA256_V6=execution.MANIFEST_SHA256_V6,
        )
        for name, fields in original.LEGACY_ROLES.items():
            with self.subTest(consumer=name):
                actual = self.fixture.import_consumers(
                    {name: fields}, execution.PROFILE_V6, pins
                )
                self.assertNotEqual(actual.returncode, 0)
                self.assertIn("exact execution-source manifest", actual.stderr)

    def test_diverse_training_rejects_dirty_source_before_original_checkout(self):
        self.fixture.source.write_bytes(b"unreviewed = True\n")
        with (
            patch.object(
                study.original, "EXECUTION_SOURCE_PROFILE", execution.PROFILE_V6
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
            study.original, "EXECUTION_SOURCE_PROFILE", execution.PROFILE_V6
        ):
            observed = evidence.integrated_sources(repositories)
            self.assertEqual(observed["chain_commit"], self.head)
            for name in evidence.REPOSITORIES - {"hepta"}:
                for field in ("commit", "tree"):
                    with self.subTest(role=name, field=field):
                        changed = copy.deepcopy(repositories)
                        changed[name]["identity"][field] = "b" * 40
                        with self.assertRaisesRegex(ValueError, "same V6 Chain"):
                            evidence.integrated_sources(changed)
        with patch.object(study.original, "EXECUTION_SOURCE_PROFILE", None):
            self.assertIsNone(evidence.integrated_sources(repositories))

    def test_identical_tree_at_a_new_commit_does_not_inherit_source_evidence(self):
        self.fixture.git(
            "-c",
            "user.name=Controlled source fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--allow-empty",
            "--quiet",
            "-m",
            "new source identity",
        )
        self.assertEqual(
            self.fixture.git("rev-parse", "HEAD^{tree}").strip(), self.tree
        )
        with self.assertRaisesRegex(ValueError, "exact integrated Chain commit"):
            execution.verify(self.fixture.chain, execution.PROFILE_V6)

    def test_reader_cannot_relabel_v5_observations_for_v6(self):
        root = self.fixture.chain.parent / "evidence"
        root.mkdir()
        repositories = {
            name: {"identity": {"commit": self.head, "tree": self.tree}}
            for name in evidence.REPOSITORIES
        }
        with (
            patch.object(
                study.original, "EXECUTION_SOURCE_PROFILE", execution.PROFILE_V6
            ),
            patch.object(study, "TRAINING_COMMIT", self.head),
            patch.object(study, "TRAINING_TREE", self.tree),
            patch.dict(os.environ, {"DIVERSE_TRAINING_CHAIN_SHA": self.head}),
            patch.object(evidence.DiverseEvidence, "command", return_value=None),
            patch.object(evidence.DiverseEvidence, "loop", return_value=None),
        ):
            current = evidence.integrated_sources(repositories)
            for selected, expected in (
                (execution.PROFILE_V5, False),
                (execution.PROFILE_V6, True),
            ):
                case = root / selected
                case.mkdir()
                (case / "final-source-diff.patch").write_bytes(b"")
                record = dict(
                    schema="hepta-neural-complete-source-diverse-v3",
                    valid=True,
                    run=evidence.original.run_identity(),
                    repositories=repositories,
                    execution_source=dict(current, profile=selected),
                )
                for name in ("source-before.json", "source-after.json"):
                    evidence.original.save(case / name, record)
                evidence.assess(case)
                report = evidence.read(case / "qualification-summary.json")
                observed = report["checks"]["complete_source"]
                self.assertIs(observed["passed"], expected)
                if not expected:
                    self.assertIn(
                        "cannot inherit historical observations", observed["error"]
                    )
                self.assertFalse(report["installation_authority"])

    def test_actual_source_collector_checks_each_v6_checkout(self):
        root = self.fixture.chain.parent / "hepta"
        root.mkdir()
        self.fixture.source.write_bytes(b"unreviewed = True\n")
        with (
            patch.object(
                study.original, "EXECUTION_SOURCE_PROFILE", execution.PROFILE_V6
            ),
            patch.object(evidence.original.ci, "git", return_value=str(root)),
            patch.object(
                evidence.original, "collect_source", return_value={"identity": {}}
            ) as collect,
        ):
            self.assertEqual(evidence.source(root / "source.json"), 1)
            # Only the Hepta identity can reach the collector: each Chain checkout
            # must fail its actual source guard before a trusted identity is read.
            self.assertEqual([call.args[0] for call in collect.call_args_list], [root])
            record = evidence.read(root / "source.json")
            self.assertFalse(record["valid"])
            self.assertNotIn("execution_source", record)

    def test_unfrozen_source_cannot_import_diverse_training(self):
        pins = dict(
            self.fixture.fixture_pins(),
            CHAIN_COMMIT_V6="UNPUBLISHED",
            CHAIN_TREE_V6=self.tree,
            MANIFEST_SHA256_V6=execution.MANIFEST_SHA256_V6,
        )
        result = self.fixture.import_consumers(
            {"hepta_neural_study_diverse_v3": {"TRAINING_COMMIT": self.head}},
            execution.PROFILE_V6,
            pins,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not been frozen", result.stderr)


if __name__ == "__main__":
    unittest.main()
