"""Reader and export mechanisms; synthetic records confer no model qualification."""

import copy
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import hepta_neural_runtime_evidence_v1 as evidence
import test_hepta_smollm_runtime_roles_v1 as role_fixture
import test_hepta_smollm_metadata_artifact_v1 as metadata_fixture


class RuntimeEvidenceControls(unittest.TestCase):
    def setUp(self):
        self.fixture = role_fixture.RuntimeRoleControls()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.roles = evidence.roles
        self.keys = {"hepta", "chain", "chain-answer-eos", "chain-observed"}
        self.old_schema = "hepta-neural-complete-source-v1"
        self.environment = dict(
            HEPTA_RUNTIME_CHAIN_SHA=evidence.bootstrap.CHAIN_COMMIT,
            HEPTA_RUNTIME_EXECUTION_PROFILE=evidence.bootstrap.PROFILE,
        )
        self.enterContext(patch.dict(os.environ, self.environment, clear=True))

    def record(self):
        rows = {
            name: {"root": str(self.fixture.root / name), "identity": {}}
            for name in self.keys
        }
        rows["chain"] = dict(
            root=str(self.fixture.historical),
            identity=dict(commit=self.fixture.old_commit),
        )
        rows["chain-runtime"] = dict(
            root=str(self.fixture.current),
            identity=dict(
                commit=evidence.bootstrap.CHAIN_COMMIT,
                tree=evidence.bootstrap.CHAIN_TREE,
                dirty=False,
            ),
        )
        return dict(
            schema=self.old_schema + evidence.SUFFIX,
            repositories=rows,
            current_runtime=self.fixture.verification,
        )

    def validate(self, record):
        evidence.validate_sources(
            record, self.old_schema, self.keys, self.fixture.config
        )

    def test_original_role_set_does_not_gain_an_ambient_runtime(self):
        record = dict(
            schema=self.old_schema, repositories={name: {} for name in self.keys}
        )
        self.assertEqual(evidence.names(self.keys, record), self.keys)
        evidence.validate_sources(
            record, self.old_schema, self.keys, {"schema": self.roles.OLD_SCHEMA}
        )
        with self.assertRaisesRegex(ValueError, "legacy evidence"):
            self.validate(record)

    def test_new_source_record_requires_the_distinct_fixed_runtime(self):
        self.validate(self.record())
        self.fixture.verify.assert_called_once_with(
            self.fixture.current, evidence.bootstrap.PROFILE
        )

    def test_each_missing_or_extra_role_is_refused(self):
        for name in self.record()["repositories"]:
            value = self.record()
            del value["repositories"][name]
            with (
                self.subTest(name=name),
                self.assertRaisesRegex(ValueError, "exact versioned"),
            ):
                self.validate(value)
        value = self.record()
        value["repositories"]["unreviewed"] = {}
        with self.assertRaisesRegex(ValueError, "exact versioned"):
            self.validate(value)

    def test_runtime_commit_tree_dirty_and_alias_cannot_inherit_old_evidence(self):
        for field, replacement in (
            ("commit", self.fixture.old_commit),
            ("tree", "0" * 40),
            ("dirty", True),
        ):
            value = copy.deepcopy(self.record())
            value["repositories"]["chain-runtime"]["identity"][field] = replacement
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(ValueError, "distinct actual"),
            ):
                self.validate(value)
        value = self.record()
        value["repositories"]["chain-runtime"]["root"] = str(self.fixture.historical)
        with self.assertRaisesRegex(ValueError, "distinct actual"):
            self.validate(value)

    def test_runtime_proof_must_match_the_fresh_checked_source(self):
        value = self.record()
        value["current_runtime"] = dict(
            self.fixture.verification, chain_commit=self.fixture.old_commit
        )
        with self.assertRaisesRegex(ValueError, "cannot inherit"):
            self.validate(value)

    def test_source_collection_is_explicit_and_preserves_failed_current_admission(self):
        value = dict(schema=self.old_schema, repositories={}, errors=[])
        with patch.object(
            evidence.roles.execution, "verify", side_effect=ValueError("changed source")
        ):
            evidence.append_runtime(
                value,
                self.fixture.root / "hepta",
                lambda *_: self.fail("collector must not run"),
                self.fixture.root / "chain-runtime",
            )
        self.assertEqual(value["schema"], self.old_schema + evidence.SUFFIX)
        self.assertEqual(value["repositories"], {})
        self.assertEqual(
            value["errors"],
            [{"repository": "chain-runtime", "error": "changed source"}],
        )

    def test_unknown_source_schema_and_partial_environment_are_refused(self):
        value = self.record()
        value["schema"] = "unknown" + evidence.SUFFIX
        with self.assertRaisesRegex(ValueError, "exact versioned"):
            self.validate(value)
        legacy = dict(
            schema=self.old_schema, repositories={name: {} for name in self.keys}
        )
        with self.assertRaisesRegex(ValueError, "legacy evidence"):
            evidence.validate_sources(
                legacy, self.old_schema, self.keys, {"schema": "unknown"}
            )
        with patch.dict(
            os.environ,
            {"HEPTA_RUNTIME_CHAIN_SHA": evidence.bootstrap.CHAIN_COMMIT},
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "explicit fixed"):
                self.validate(self.record())

    def test_forward_source_roles_fail_before_ready_or_model_claims(self):
        phase = dict(
            forward_profile=evidence.bootstrap.PROFILE,
            study_profile="neural-v1",
            runtime_chain=str(self.fixture.historical),
        )
        worker = dict(
            chain=str(self.fixture.current),
            runtime_snapshot=dict(
                path=self.fixture.config["runtime_snapshot"],
                sha256=self.fixture.config["runtime_snapshot_sha256"],
            ),
        )
        with self.assertRaisesRegex(ValueError, "actual forward"):
            evidence.verify_forward(
                self.fixture.config,
                phase,
                worker,
                {},
                lambda *_: self.fail("Ready cannot be consumed"),
            )


class RuntimeMetadataControls(unittest.TestCase):
    def setUp(self):
        self.fixture = metadata_fixture.MetadataArtifactTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fields = dict(
            schema="hepta-material-runtime-evidence-index-v1",
            chain="cfa57cd04751427451302b5c10539b3984d7f8db",
            runtime_chain=evidence.bootstrap.CHAIN_COMMIT,
            runtime_profile=evidence.bootstrap.PROFILE,
        )

    def test_new_export_retains_all_declared_current_runtime_bytes_without_authority(
        self,
    ):
        names = (
            "runtime-chain-source.txt",
            "runtime-chain-source-after.txt",
            "runtime-execution-source.json",
            "runtime-execution-source-after.json",
        )
        for name in names:
            self.fixture.file(
                name, b"{}" if name.endswith(".json") else b"exact source\n"
            )
        self.fixture.index(**self.fields)
        result = self.fixture.run_export()
        self.assertEqual(set(result["files"]), set(names) | {"evidence-index.json"})
        self.assertEqual(
            result["schema"], "hepta-model-metadata-artifact-material-bridge-v1"
        )
        self.assertFalse(result["product_qualification"])
        self.assertFalse(result["independent_payload_replay_available"])
        for name in names:
            self.assertEqual(
                (self.fixture.output / name).read_bytes(),
                (self.fixture.root / name).read_bytes(),
            )

    def test_swapped_unknown_and_incomplete_runtime_index_roles_refuse(self):
        for changes in (
            {"runtime_chain": self.fields["chain"]},
            {"chain": evidence.bootstrap.CHAIN_COMMIT},
            {"runtime_profile": "old"},
            {"schema": "unknown"},
        ):
            self.fixture.index(**dict(self.fields, **changes))
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.fixture.run_export()
        missing = dict(self.fields)
        del missing["runtime_profile"]
        self.fixture.index(**missing)
        with self.assertRaises((KeyError, ValueError)):
            self.fixture.run_export()

    def test_new_runtime_file_tamper_cannot_change_original_index(self):
        path = self.fixture.file("runtime-execution-source.json", b"{}")
        self.fixture.index(**self.fields)
        path.write_bytes(b'{"changed":true}')
        with self.assertRaisesRegex(ValueError, "differs from original index"):
            self.fixture.run_export()
        self.assertFalse(self.fixture.output.exists())

    def test_legacy_index_cannot_add_a_runtime_without_explicit_version(self):
        self.fixture.index(runtime_chain=evidence.bootstrap.CHAIN_COMMIT)
        with self.assertRaisesRegex(ValueError, "original source-bound"):
            self.fixture.run_export()


class CompleteForwardReadbackControls(unittest.TestCase):
    def setUp(self):
        import test_hepta_neural_forward_v2 as forward_fixture

        self.forward_fixture = forward_fixture
        self.projection = forward_fixture.ProjectionTests()
        self.projection.setUp()
        self.addCleanup(self.projection.doCleanups)
        self.roles = role_fixture.RuntimeRoleControls()
        self.roles.setUp()
        self.addCleanup(self.roles.doCleanups)
        self.enterContext(patch.object(evidence, "bootstrap", forward_fixture.BOOT))
        self.enterContext(
            patch.object(
                evidence,
                "__file__",
                str(self.projection.scripts / "hepta_neural_runtime_evidence_v1.py"),
            )
        )
        self.enterContext(
            patch.dict(
                os.environ,
                {
                    "HEPTA_RUNTIME_CHAIN_SHA": evidence.bootstrap.CHAIN_COMMIT,
                    "HEPTA_RUNTIME_EXECUTION_PROFILE": evidence.bootstrap.PROFILE,
                },
                clear=True,
            )
        )
        self.roles.git.side_effect = lambda *args, **kwargs: (
            evidence.forward.OBSERVERS["neural-v1"][0] if args[0] == "rev-parse" else ""
        )
        self.enterContext(patch.object(evidence.roles.execution, "verify_selected"))
        profiles = "codex-rs/hepta-learning-artifacts/profiles"
        source = forward_fixture.ROOT / profiles / evidence.forward.CALLER_MANIFEST_NAME
        self.write(self.projection.root / profiles / source.name, source.read_bytes())
        self.config = dict(self.roles.config, chain=str(self.projection.chain))
        self.worker = copy.deepcopy(self.projection.config)
        self.worker["runtime_snapshot"] = {
            "path": self.config["runtime_snapshot"],
            "sha256": self.config["runtime_snapshot_sha256"],
        }
        ready_fixture = forward_fixture.ReadyTests()
        ready_fixture.setUp()
        self.parent = dict(
            adapter="fixed-parent",
            file_sha256="f" * 64,
            contract=evidence.roles.CONTRACT,
            generation=1,
        )
        self.plan = dict(
            ready_fixture.plan,
            material_bridge=self.config["material_runtime_bridge"],
            runtime_snapshot_sha256=self.config["runtime_snapshot_sha256"],
        )
        self.worker["worker_plan"] = self.object("worker-plan.json", self.plan)
        self.ready = dict(
            ready_fixture.ready,
            actual_loaded_parent=self.parent["adapter"],
            file_sha256=self.parent["file_sha256"],
            contract=self.parent["contract"],
            generation=self.parent["generation"],
            runtime_snapshot_sha256=self.config["runtime_snapshot_sha256"],
            runtime_source_set_sha256=forward_fixture.sha(
                forward_fixture.encoded(
                    {
                        Path(path).name: value
                        for path, value in self.projection.complete.items()
                    }
                )
            ),
        )
        self.phase = dict(
            forward_profile=evidence.bootstrap.PROFILE,
            study_profile="neural-v1",
            runtime_chain=str(self.projection.chain),
            training_chain=str(self.roles.historical),
        )
        self.actual = dict(
            schema=evidence.bootstrap.SCHEMA + "-result",
            source_sha256=self.worker["source_sha256"],
            parent=self.parent,
            prefix_chain=[],
        )
        self.reads = []
        self.replace_ready([copy.deepcopy(self.ready) for _ in range(9)])

    def write(self, path, raw):
        return self.forward_fixture.pin(path, raw)

    def object(self, name, value):
        return self.write(
            self.projection.root / name, self.forward_fixture.encoded(value)
        )

    def replace_ready(self, values):
        self.actual["prefix_chain"] = []
        self.ready_paths = []
        for index, value in enumerate(values):
            pinned = self.object(f"ready-{index}.json", value)
            self.ready_paths.append(pinned["path"])
            item = dict(pinned, observation=value)
            if index < 8:
                self.actual["prefix_chain"].append(
                    self.object(f"prefix-{index}.json", {"actual_ready": item})
                )
            else:
                self.actual["last_ready"] = item

    def consume(self, pin):
        self.reads.append(pin["path"])
        return evidence.bootstrap.object_at(pin, 512 * 1024)

    def verify(self):
        evidence.verify_forward(
            self.config, self.phase, self.worker, self.actual, self.consume
        )

    def test_all_nine_raw_ready_files_and_fifteen_sources_reach_the_reader(self):
        self.verify()
        self.assertEqual(
            [path for path in self.reads if path in self.ready_paths], self.ready_paths
        )
        self.assertEqual(len(self.projection.complete), 15)

    def test_each_self_rehashed_ready_still_requires_the_fixed_dual_identity(self):
        for index in range(9):
            values = [copy.deepcopy(self.ready) for _ in range(9)]
            values[index]["material_runtime_bridge"]["execution_runtime_source"] = (
                "0" * 64
            )
            self.replace_ready(values)
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.verify()

    def test_late_ready_or_source_tamper_cannot_inherit_the_prior_readback(self):
        self.verify()
        path = Path(self.ready_paths[-1])
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaises(ValueError):
            self.verify()
        self.replace_ready([copy.deepcopy(self.ready) for _ in range(9)])
        source = self.projection.chain / evidence.bootstrap.RUNTIME_PATHS[0]
        source.write_bytes(source.read_bytes() + b"tamper")
        self.reads.clear()
        with self.assertRaises(ValueError):
            self.verify()
        self.assertEqual(self.reads, [])

    def test_new_complete_source_requires_input_but_historical_scope_stays_independent(
        self,
    ):
        import hepta_neural_evidence_v1 as original

        base = self.projection.root / "source-readback"
        base.mkdir()
        keys = {"hepta", "chain", "chain-answer-eos", "chain-observed"}
        for schema, expected in (
            ("hepta-neural-complete-source-v1", True),
            ("hepta-neural-complete-source-v1" + evidence.SUFFIX, False),
        ):
            root = base / schema
            root.mkdir()
            (root / "final-source-diff.patch").write_bytes(b"")
            names = keys | ({"chain-runtime"} if not expected else set())
            record = dict(
                schema=schema,
                valid=True,
                run=original.run_identity(),
                repositories={name: {"identity": {}} for name in names},
            )
            for name in ("source-before.json", "source-after.json"):
                original.save(root / name, record)
            with (
                patch.object(original.Evidence, "command", return_value=None),
                patch.object(original.Evidence, "loop", return_value=None),
            ):
                original.assess(root)
            report = original.read(root / "qualification-summary.json")
            self.assertIs(report["checks"]["complete_source"]["passed"], expected)
            self.assertFalse(report["installation_authority"])
            if not expected:
                self.assertIn(
                    "native-input.json", report["checks"]["complete_source"]["error"]
                )


if __name__ == "__main__":
    unittest.main()
