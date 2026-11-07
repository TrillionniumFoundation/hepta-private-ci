"""Closed V12/V13 role selection controls, without training or model execution."""

import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import patch

import hepta_neural_runtime_evidence_v1 as evidence
import hepta_smollm_execution_source_v1 as execution
import hepta_smollm_runtime_roles_v1 as roles
import test_hepta_smollm_runtime_roles_v1 as fixtures
import test_hepta_smollm_metadata_artifact_v1 as metadata_fixture

ROOT = Path(__file__).resolve().parents[1]
GOOD = dict(
    HEPTA_RUNTIME_EXECUTION_PROFILE=execution.PROFILE_V13,
    HEPTA_RUNTIME_CHAIN_SHA=execution.CHAIN_COMMIT_V13,
)


class ProfileRoleControls(unittest.TestCase):
    def test_absence_partial_unknown_and_cross_version_tuples_are_explicit(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(roles.selected_runtime())
            self.assertEqual(roles.runtime_contract(), (roles.bridge, None))
        old = dict(
            HEPTA_RUNTIME_EXECUTION_PROFILE=roles.bridge.PROFILE,
            HEPTA_RUNTIME_CHAIN_SHA=roles.bridge.CHAIN_COMMIT,
        )
        for environment in (old, GOOD):
            with patch.dict(os.environ, environment, clear=True):
                self.assertTrue(roles.selected_runtime())
        bad = [{k: v for k, v in GOOD.items() if k != omit} for omit in GOOD]
        bad.extend(
            [
                dict(GOOD, HEPTA_RUNTIME_CHAIN_SHA=roles.bridge.CHAIN_COMMIT),
                dict(old, HEPTA_RUNTIME_CHAIN_SHA=execution.CHAIN_COMMIT_V13),
                dict(GOOD, HEPTA_RUNTIME_EXECUTION_PROFILE="unregistered"),
                dict(GOOD, HEPTA_RUNTIME_CHAIN_SHA="0" * 40),
            ]
        )
        for environment in bad:
            with (
                self.subTest(environment=environment),
                patch.dict(os.environ, environment, clear=True),
            ):
                with self.assertRaisesRegex(ValueError, "explicit fixed"):
                    roles.runtime_contract()

    def test_fixed_parent_and_callers_ignore_import_search_shadows(self):
        with tempfile.TemporaryDirectory() as temporary:
            shadow = Path(temporary)
            canary = shadow / "executed"
            (shadow / "hepta_neural_study_forward_v3.py").write_text(
                "from pathlib import Path\nPath(" + repr(str(canary)) + ").touch()\n"
            )
            fake = ModuleType("hepta_neural_study_forward_v3")
            fake.__file__ = str(ROOT / "scripts/hepta_neural_study_forward_v3.py")
            with (
                patch.dict(os.environ, GOOD, clear=True),
                patch.object(sys, "path", [str(shadow), *sys.path]),
                patch.dict(sys.modules, {fake.__name__: fake}),
            ):
                current, parent = roles.runtime_contract()
            self.assertEqual(current.PROFILE, execution.PROFILE_V13)
            self.assertEqual(
                parent.caller_path(),
                ROOT / "scripts/hepta_neural_forward_v13/hepta_neural_forward_v2.py",
            )
            self.assertFalse(canary.exists())

    def test_parent_bytes_cannot_be_rebound_by_a_local_manifest_or_origin(self):
        with tempfile.TemporaryDirectory() as temporary:
            scripts = Path(temporary).resolve() / "scripts"
            scripts.mkdir()
            parent = scripts / "hepta_neural_study_forward_v3.py"
            canary = scripts / "executed"
            parent.write_text(
                "from pathlib import Path\nPath(" + repr(str(canary)) + ").touch()\n"
            )
            with (
                patch.dict(os.environ, GOOD, clear=True),
                patch.object(
                    roles, "__file__", str(scripts / "hepta_smollm_runtime_roles_v1.py")
                ),
            ):
                with self.assertRaisesRegex(ValueError, "caller bytes changed"):
                    roles.runtime_contract()
            self.assertFalse(canary.exists())

    def test_v13_current_validation_passes_only_the_original_historical_training_role(
        self,
    ):
        fixture = fixtures.RuntimeRoleControls()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        verification = dict(
            profile=execution.PROFILE_V13,
            chain_commit=execution.CHAIN_COMMIT_V13,
            chain_tree=execution.CHAIN_TREE_V13,
            product_qualification=False,
        )
        fixture.verify.return_value = verification
        with patch.dict(os.environ, GOOD, clear=True):
            historical, observation = roles.native_roles(
                fixture.config, fixture.historical, fixture.old_commit
            )
        self.assertEqual(historical, fixture.historical)
        self.assertEqual(observation["historical_chain"]["commit"], fixture.old_commit)
        self.assertEqual(
            observation["current_runtime"],
            dict(verification, root=str(fixture.current)),
        )
        fixture.verify.assert_called_once_with(fixture.current, execution.PROFILE_V13)
        self.assertFalse(observation["installation_authorized"])

    def test_v13_complete_source_record_refuses_old_tuple_and_aliased_roles(self):
        fixture = fixtures.RuntimeRoleControls()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        verification = dict(
            profile=execution.PROFILE_V13,
            chain_commit=execution.CHAIN_COMMIT_V13,
            chain_tree=execution.CHAIN_TREE_V13,
            product_qualification=False,
        )
        fixture.verify.return_value = verification
        keys = {"hepta", "chain", "chain-answer-eos", "chain-observed"}
        rows = {name: dict(root=str(fixture.root / name), identity={}) for name in keys}
        rows["chain"] = dict(
            root=str(fixture.historical), identity=dict(commit=fixture.old_commit)
        )
        rows["chain-runtime"] = dict(
            root=str(fixture.current),
            identity=dict(
                commit=execution.CHAIN_COMMIT_V13,
                tree=execution.CHAIN_TREE_V13,
                dirty=False,
            ),
        )
        record = dict(
            schema="hepta-neural-complete-source-v1" + evidence.SUFFIX,
            repositories=rows,
            current_runtime=verification,
        )
        with patch.dict(os.environ, GOOD, clear=True):
            evidence.validate_sources(
                record, "hepta-neural-complete-source-v1", keys, fixture.config
            )
            for field, replacement in (
                ("commit", roles.bridge.CHAIN_COMMIT),
                ("tree", roles.bridge.CHAIN_TREE),
                ("dirty", True),
            ):
                changed = copy.deepcopy(record)
                changed["repositories"]["chain-runtime"]["identity"][field] = (
                    replacement
                )
                with self.subTest(field=field), self.assertRaises(ValueError):
                    evidence.validate_sources(
                        changed, "hepta-neural-complete-source-v1", keys, fixture.config
                    )
            changed = copy.deepcopy(record)
            changed["repositories"]["chain-runtime"]["root"] = str(fixture.historical)
            with self.assertRaises(ValueError):
                evidence.validate_sources(
                    changed, "hepta-neural-complete-source-v1", keys, fixture.config
                )


class MetadataProfileControls(unittest.TestCase):
    def setUp(self):
        self.fixture = metadata_fixture.MetadataArtifactTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fields = dict(
            schema="hepta-material-runtime-evidence-index-v1",
            chain="cfa57cd04751427451302b5c10539b3984d7f8db",
            runtime_chain=execution.CHAIN_COMMIT_V13,
            runtime_profile=execution.PROFILE_V13,
        )

    def test_new_metadata_tuple_is_explicit_and_never_issues_authority(self):
        self.fixture.file("runtime-chain-source.txt", b"exact source observation\n")
        self.fixture.index(**self.fields)
        result = self.fixture.run_export()
        self.assertEqual(result["runtime_chain"], execution.CHAIN_COMMIT_V13)
        self.assertEqual(result["runtime_profile"], execution.PROFILE_V13)
        self.assertFalse(result["product_qualification"])
        self.assertFalse(result["independent_payload_replay_available"])

    def test_cross_version_or_missing_metadata_roles_refuse(self):
        for update in (
            dict(runtime_chain=roles.bridge.CHAIN_COMMIT),
            dict(runtime_profile=roles.bridge.PROFILE),
            dict(chain=execution.CHAIN_COMMIT_V13),
            dict(runtime_profile="unknown"),
        ):
            self.fixture.index(**dict(self.fields, **update))
            with self.subTest(update=update), self.assertRaises(ValueError):
                self.fixture.run_export()
        missing = dict(self.fields)
        del missing["runtime_profile"]
        self.fixture.index(**missing)
        with self.assertRaises((ValueError, KeyError)):
            self.fixture.run_export()


if __name__ == "__main__":
    unittest.main()
