"""Exercise distinct real Git identities; these controls do not qualify a model."""

import builtins
import copy
import importlib
import json
import subprocess
import unittest
from unittest.mock import patch

import hepta_smollm_execution_source_v1 as execution
import hepta_smollm_public_initial_v2 as material
import test_hepta_smollm_execution_source_v1 as original


class ExecutionSourceV2Tests(unittest.TestCase):
    def setUp(self):
        self.fixture = original.ExecutionSourceTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.v1_bytes = self.fixture.manifest_path.read_bytes()
        self.fixture.source.write_bytes(b"fixture_source = 2\n")
        self.fixture.git("add", "scripts")
        self.fixture.commit()
        self.head = self.fixture.git("rev-parse", "HEAD").strip()
        self.assertNotEqual(self.head, self.fixture.manifest["chain_commit"])
        self.manifest = copy.deepcopy(self.fixture.manifest)
        self.manifest.update(profile=execution.PROFILE_V2, chain_commit=self.head)
        self.manifest["files"]["scripts/controlled.py"] = dict(
            size=self.fixture.source.stat().st_size,
            sha256=execution.digest(self.fixture.source.read_bytes()),
        )
        self.path = self.fixture.profiles / execution.MANIFEST_NAME_V2
        self.enterContext(patch.object(execution, "CHAIN_COMMIT_V2", self.head))
        self.repin(self.manifest)

    def repin(self, value):
        self.path.write_text(json.dumps(value))
        self.enterContext(
            patch.object(
                execution,
                "MANIFEST_SHA256_V2",
                execution.digest(self.path.read_bytes()),
            )
        )

    def fixture_pins(self):
        return dict(
            self.fixture.fixture_pins(),
            CHAIN_COMMIT_V2=execution.CHAIN_COMMIT_V2,
            MANIFEST_SHA256_V2=execution.MANIFEST_SHA256_V2,
        )

    def test_two_profiles_verify_only_their_own_committed_checkout(self):
        result = execution.verify(self.fixture.chain, execution.PROFILE_V2)
        self.assertEqual(result["profile"], execution.PROFILE_V2)
        self.assertEqual(result["chain_commit"], self.head)
        self.assertEqual(result["manifest_sha256"], execution.MANIFEST_SHA256_V2)
        self.assertEqual(
            [
                result[key]
                for key in (
                    "model_compatibility_changed",
                    "product_qualification",
                    "installation_authorized",
                )
            ],
            [False, False, False],
        )
        self.assertEqual(
            execution.checked_manifest(execution.PROFILE), self.fixture.manifest
        )
        self.assertEqual(self.fixture.manifest_path.read_bytes(), self.v1_bytes)
        with self.assertRaisesRegex(ValueError, "exact integrated Chain commit"):
            execution.verify(self.fixture.chain, execution.PROFILE)
        self.fixture.git("checkout", "--quiet", self.fixture.manifest["chain_commit"])
        execution.verify(self.fixture.chain, execution.PROFILE)
        with self.assertRaisesRegex(ValueError, "exact integrated Chain commit"):
            execution.verify(self.fixture.chain, execution.PROFILE_V2)

    def test_six_selected_consumers_bind_v2_without_changing_defaults(self):
        result = self.fixture.import_consumers(
            original.LEGACY_ROLES, execution.PROFILE_V2, self.fixture_pins()
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            {
                name: dict.fromkeys(fields, self.head)
                for name, fields in original.LEGACY_ROLES.items()
            },
        )
        default = self.fixture.import_consumers(original.LEGACY_ROLES, None)
        self.assertEqual(default.returncode, 0, default.stderr)
        self.assertEqual(json.loads(default.stdout), original.LEGACY_ROLES)

    def test_each_consumer_refuses_unfrozen_v2_before_chain_import(self):
        pins = dict(
            self.fixture_pins(),
            CHAIN_COMMIT_V2="UNPUBLISHABLE_PENDING_FINAL_CHAIN_SHA",
        )
        for name, fields in original.LEGACY_ROLES.items():
            with self.subTest(consumer=name):
                result = self.fixture.import_consumers(
                    {name: fields}, execution.PROFILE_V2, pins
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("not been frozen", result.stderr)

    def test_v2_rejects_v1_identity_mixed_source_and_manifest_tamper(self):
        for field, changed in (
            ("profile", execution.PROFILE),
            ("chain_commit", self.fixture.manifest["chain_commit"]),
            ("schema", "unreviewed-schema"),
            ("historical_sources_sha256", "a" * 64),
            ("extra", True),
        ):
            with self.subTest(field=field):
                self.repin(dict(self.manifest, **{field: changed}))
                with self.assertRaises(ValueError):
                    execution.verify(self.fixture.chain, execution.PROFILE_V2)
        self.repin(self.manifest)
        self.path.write_bytes(self.path.read_bytes() + b" ")
        result = self.fixture.import_consumers(
            original.LEGACY_ROLES, execution.PROFILE_V2, self.fixture_pins()
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exact execution-source manifest", result.stderr)

    def test_old_v1_forward_input_cannot_be_relabelled_as_v2_execution(self):
        forward = importlib.import_module("hepta_neural_forward_v1")
        args = self.fixture.forward_input(
            forward, self.fixture.manifest["chain_commit"]
        )
        with (
            patch.object(forward, "CHAIN", self.head),
            patch.object(forward, "EXECUTION_SOURCE_PROFILE", execution.PROFILE_V2),
            patch.object(forward, "arm_parent") as parent,
            patch.object(forward.importlib, "import_module") as importer,
        ):
            with self.assertRaisesRegex(
                ValueError, "original source and whole-phase budget"
            ):
                forward.run(args)
            parent.assert_not_called()
            importer.assert_not_called()

    def test_actual_v2_forward_rejects_dirty_source_before_worker_import(self):
        forward = importlib.import_module("hepta_neural_forward_v1")
        args = self.fixture.forward_input(forward, self.head)
        self.fixture.source.write_bytes(b"unreviewed = True\n")
        with (
            patch.object(forward, "CHAIN", self.head),
            patch.object(forward, "EXECUTION_SOURCE_PROFILE", execution.PROFILE_V2),
            patch.object(forward, "arm_parent"),
            patch.object(forward, "birth"),
            patch.object(forward.importlib, "import_module") as importer,
        ):
            with self.assertRaises(subprocess.CalledProcessError):
                forward.run(args)
            importer.assert_not_called()

    def test_v2_derive_rejects_old_checkout_before_first_chain_import(self):
        self.fixture.git("checkout", "--quiet", self.fixture.manifest["chain_commit"])
        output = self.fixture.chain.parent / "not-created"
        original_import = builtins.__import__

        def guarded_import(name, *args, **kwargs):
            if name.startswith("llm_"):
                raise AssertionError("Chain import occurred before source refusal")
            return original_import(name, *args, **kwargs)

        with (
            patch.object(material, "PROFILES", self.fixture.profiles),
            patch("builtins.__import__", side_effect=guarded_import),
        ):
            with self.assertRaisesRegex(ValueError, "exact integrated Chain commit"):
                material.derive(
                    self.fixture.chain,
                    self.fixture.chain.parent,
                    output,
                    False,
                    execution.PROFILE_V2,
                )
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
