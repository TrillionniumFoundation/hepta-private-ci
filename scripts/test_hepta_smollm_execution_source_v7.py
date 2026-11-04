"""A new source identity requires new evidence even when execution bytes match."""

import copy
import json
import os
import unittest
from unittest.mock import patch

import hepta_neural_evidence_diverse_v3 as evidence
import hepta_neural_study_diverse_v3 as study
import hepta_smollm_execution_source_v1 as execution
import test_hepta_smollm_execution_source_v1 as original


class ExecutionSourceV7Tests(unittest.TestCase):
    def setUp(self):
        self.fixture = original.ExecutionSourceTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.v6 = execution.checked_manifest(execution.PROFILE_V6)
        self.historical = {
            p.name: p.read_bytes()
            for p in self.fixture.profiles.iterdir()
            if p.name != execution.MANIFEST_NAME_V7
        }
        # Change only source-control metadata, outside the execution closure.
        # Equal execution bytes cannot transfer the previous source's evidence.
        metadata = self.fixture.chain / ".github/workflows/source-identity.yml"
        metadata.parent.mkdir(parents=True)
        metadata.write_text("observed_controls: 6\n")
        self.fixture.git("add", ".github")
        self.fixture.commit()
        self.head = self.fixture.git("rev-parse", "HEAD").strip()
        self.tree = self.fixture.git("rev-parse", "HEAD^{tree}").strip()
        self.manifest = dict(
            self.v6,
            profile=execution.PROFILE_V7,
            chain_commit=self.head,
            chain_tree=self.tree,
        )
        self.path = self.fixture.profiles / execution.MANIFEST_NAME_V7
        self.path.write_text(json.dumps(self.manifest))
        for name, value in (
            ("CHAIN_COMMIT_V7", self.head),
            ("CHAIN_TREE_V7", self.tree),
            ("MANIFEST_SHA256_V7", execution.digest(self.path.read_bytes())),
        ):
            self.enterContext(patch.object(execution, name, value))

    def pins(self):
        return dict(
            self.fixture.fixture_pins(),
            CHAIN_COMMIT_V6=self.v6["chain_commit"],
            CHAIN_TREE_V6=self.v6["chain_tree"],
            MANIFEST_SHA256_V6=execution.MANIFEST_SHA256_V6,
            CHAIN_COMMIT_V7=self.head,
            CHAIN_TREE_V7=self.tree,
            MANIFEST_SHA256_V7=execution.MANIFEST_SHA256_V7,
        )

    def repositories(self):
        return {
            name: {"identity": {"commit": self.head, "tree": self.tree}}
            for name in evidence.REPOSITORIES
        }

    def test_current_and_historical_v6_verify_only_their_own_source(self):
        current = execution.verify(self.fixture.chain, execution.PROFILE_V7)
        self.assertEqual(
            (current["chain_commit"], current["chain_tree"]), (self.head, self.tree)
        )
        self.assertEqual(
            [current[key] for key in (
                "model_compatibility_changed", "product_qualification",
                "installation_authorized",
            )],
            [False, False, False],
        )
        self.fixture.git("checkout", "--quiet", "--detach", self.v6["chain_commit"])
        try:
            historical = execution.verify(self.fixture.chain, execution.PROFILE_V6)
            self.assertEqual(historical["chain_commit"], self.v6["chain_commit"])
            with self.assertRaisesRegex(ValueError, "exact integrated Chain commit"):
                execution.verify(self.fixture.chain, execution.PROFILE_V7)
        finally:
            self.fixture.git("checkout", "--quiet", "--detach", self.head)
        self.assertEqual(
            {name: (self.fixture.profiles / name).read_bytes()
             for name in self.historical},
            self.historical,
        )

    def test_unchanged_execution_closure_cannot_inherit_v6_identity_or_tree(self):
        self.assertEqual(self.manifest["files"], self.v6["files"])
        self.assertNotEqual(self.tree, self.v6["chain_tree"])
        with self.assertRaisesRegex(ValueError, "exact integrated Chain commit"):
            execution.verify(self.fixture.chain, execution.PROFILE_V6)
        changed = dict(self.manifest, chain_tree=self.v6["chain_tree"])
        self.path.write_text(json.dumps(changed))
        with patch.object(execution, "MANIFEST_SHA256_V7",
                          execution.digest(self.path.read_bytes())):
            with self.assertRaisesRegex(ValueError, "exact integrated Chain tree"):
                execution.verify(self.fixture.chain, execution.PROFILE_V7)

    def test_identical_tree_at_another_commit_requires_its_own_source_evidence(self):
        self.fixture.git(
            "-c", "user.name=Controlled source fixture",
            "-c", "user.email=fixture@example.invalid",
            "-c", "commit.gpgsign=false", "commit", "--allow-empty", "--quiet",
            "-m", "another source identity",
        )
        self.assertEqual(self.fixture.git("rev-parse", "HEAD^{tree}").strip(), self.tree)
        with self.assertRaisesRegex(ValueError, "exact integrated Chain commit"):
            execution.verify(self.fixture.chain, execution.PROFILE_V7)

    def test_all_consumers_select_one_current_source_and_keep_explicit_v6(self):
        roles = dict(original.LEGACY_ROLES)
        roles["hepta_neural_study_diverse_v3"] = {
            "TRAINING_COMMIT": self.head, "TRAINING_TREE": self.tree,
        }
        for profile, commit, tree in (
            (execution.PROFILE_V7, self.head, self.tree),
            (execution.PROFILE_V6, self.v6["chain_commit"], self.v6["chain_tree"]),
        ):
            with self.subTest(profile=profile):
                result = self.fixture.import_consumers(roles, profile, self.pins())
                self.assertEqual(result.returncode, 0, result.stderr)
                expected = {
                    name: dict.fromkeys(fields, commit)
                    for name, fields in original.LEGACY_ROLES.items()
                }
                expected["hepta_neural_study_diverse_v3"] = {
                    "TRAINING_COMMIT": commit, "TRAINING_TREE": tree,
                }
                self.assertEqual(json.loads(result.stdout), expected)

    def test_tampered_v7_manifest_refuses_every_current_consumer(self):
        pins = self.pins()
        self.path.write_bytes(self.path.read_bytes() + b" ")
        roles = dict(original.LEGACY_ROLES)
        roles["hepta_neural_study_diverse_v3"] = {"TRAINING_COMMIT": self.head}
        for name, fields in roles.items():
            with self.subTest(consumer=name):
                result = self.fixture.import_consumers(
                    {name: fields}, execution.PROFILE_V7, pins
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("exact execution-source manifest", result.stderr)
        historical = self.fixture.import_consumers(roles, execution.PROFILE_V6, pins)
        self.assertEqual(historical.returncode, 0, historical.stderr)

    def test_reader_rejects_v6_in_every_current_chain_role(self):
        repositories = self.repositories()
        with patch.object(study.original, "EXECUTION_SOURCE_PROFILE", execution.PROFILE_V7):
            self.assertEqual(evidence.integrated_sources(repositories)["chain_commit"], self.head)
            for role in evidence.REPOSITORIES - {"hepta"}:
                for field in ("commit", "tree"):
                    with self.subTest(role=role, field=field):
                        changed = copy.deepcopy(repositories)
                        changed[role]["identity"][field] = self.v6["chain_" + field]
                        with self.assertRaisesRegex(ValueError, "same V7 Chain"):
                            evidence.integrated_sources(changed)

    def test_current_evidence_rejects_v6_or_missing_profile_even_with_current_roles(self):
        root = self.fixture.chain.parent / "evidence"
        root.mkdir()
        repositories = self.repositories()
        with (
            patch.object(study.original, "EXECUTION_SOURCE_PROFILE", execution.PROFILE_V7),
            patch.object(study, "TRAINING_COMMIT", self.head),
            patch.object(study, "TRAINING_TREE", self.tree),
            patch.dict(os.environ, {"DIVERSE_TRAINING_CHAIN_SHA": self.head}),
            patch.object(evidence.DiverseEvidence, "command", return_value=None),
            patch.object(evidence.DiverseEvidence, "loop", return_value=None),
        ):
            current = evidence.integrated_sources(repositories)
            for selected, expected in (
                (execution.PROFILE_V6, False), (None, False),
                (execution.PROFILE_V7, True),
            ):
                case = root / (selected or "missing")
                case.mkdir()
                (case / "final-source-diff.patch").write_bytes(b"")
                record = dict(
                    schema="hepta-neural-complete-source-diverse-v3",
                    valid=True, run=evidence.original.run_identity(),
                    repositories=repositories,
                )
                if selected is not None:
                    record["execution_source"] = dict(current, profile=selected)
                for name in ("source-before.json", "source-after.json"):
                    evidence.original.save(case / name, record)
                evidence.assess(case)
                report = evidence.read(case / "qualification-summary.json")
                observed = report["checks"]["complete_source"]
                self.assertIs(observed["passed"], expected)
                if not expected:
                    self.assertIn("cannot inherit historical observations", observed["error"])
                self.assertFalse(report["installation_authority"])

    def test_source_collector_checks_current_chain_before_collecting_identity(self):
        root = self.fixture.chain.parent / "hepta"
        root.mkdir()
        self.fixture.source.write_bytes(b"unreviewed = True\n")
        with (
            patch.object(study.original, "EXECUTION_SOURCE_PROFILE", execution.PROFILE_V7),
            patch.object(evidence.original.ci, "git", return_value=str(root)),
            patch.object(evidence.original, "collect_source", return_value={"identity": {}}) as collect,
        ):
            self.assertEqual(evidence.source(root / "source.json"), 1)
            self.assertEqual([call.args[0] for call in collect.call_args_list], [root])
            record = evidence.read(root / "source.json")
            self.assertFalse(record["valid"])
            self.assertNotIn("execution_source", record)

    def test_unfrozen_current_profile_refuses_before_training_import(self):
        pins = dict(self.pins(), CHAIN_COMMIT_V7="UNPUBLISHED")
        result = self.fixture.import_consumers(
            {"hepta_neural_study_diverse_v3": {"TRAINING_COMMIT": self.head}},
            execution.PROFILE_V7, pins,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not been frozen", result.stderr)


if __name__ == "__main__":
    unittest.main()
