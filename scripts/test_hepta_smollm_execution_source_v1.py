"""Closed source controls use a tiny Git fixture, never model qualification."""

import copy
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import hepta_smollm_execution_source_v1 as execution
import hepta_smollm_public_initial_v2 as material


LEGACY_ROLES = {
    "hepta_smollm_three_rounds_v2": {
        "CHAIN_COMMIT": "c96022b897c1235fdbdbfcfa32764403511c6aab"
    },
    "hepta_smollm_observed_execution_v1": {
        "CHAIN_COMMIT": "ad490ed4b1132a333159fd76702809fd248a4462"
    },
    "hepta_smollm_live_control_v1": {
        "CHAIN_COMMIT": "ad490ed4b1132a333159fd76702809fd248a4462"
    },
    "hepta_smollm_answer_eos_research_v3": {
        "CHAIN_COMMIT": "9035171271e9f437b7224b53532f41a2b2894be7"
    },
    "hepta_neural_study_v1": {
        "TRAINING": "ad490ed4b1132a333159fd76702809fd248a4462",
        "RUNTIME": "c96022b897c1235fdbdbfcfa32764403511c6aab",
    },
    "hepta_neural_forward_v1": {"CHAIN": "c96022b897c1235fdbdbfcfa32764403511c6aab"},
}


class ExecutionSourceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name).resolve()
        self.chain, self.profiles = root / "chain", root / "profiles"
        (self.chain / "scripts").mkdir(parents=True)
        self.profiles.mkdir()
        self.source = self.chain / "scripts/controlled.py"
        self.source.write_bytes(b"fixture_source = True\n")
        self.git("init", "--quiet")
        self.git("add", "scripts")
        self.commit()
        head = self.git("rev-parse", "HEAD").strip()
        historical = {
            "schema": "hepta-smollm-public-initial-sources-v2",
            "chain_commit": "historical-fixture",
            "files": {"scripts/controlled.py": {"size": 1, "sha256": "0" * 64}},
        }
        self.historical = self.profiles / "smollm2-public-initial-v2.sources.json"
        self.historical.write_text(json.dumps(historical))
        self.profile = self.profiles / "smollm2-public-initial-v2.profile"
        self.profile.write_bytes(b"immutable controlled model compatibility\n")
        self.manifest = {
            "schema": "hepta-smollm-public-initial-execution-sources-v1",
            "profile": execution.PROFILE,
            "chain_commit": head,
            "historical_profile_sha256": execution.digest(self.profile.read_bytes()),
            "historical_sources_sha256": execution.digest(self.historical.read_bytes()),
            "files": {
                "scripts/controlled.py": {
                    "size": self.source.stat().st_size,
                    "sha256": execution.digest(self.source.read_bytes()),
                },
            },
        }
        self.manifest_path = self.profiles / execution.MANIFEST_NAME
        for name, value in (
            ("PROFILES", self.profiles),
            ("CHAIN_COMMIT", head),
            ("HISTORICAL_PROFILE_SHA256", self.manifest["historical_profile_sha256"]),
            ("HISTORICAL_SOURCES_SHA256", self.manifest["historical_sources_sha256"]),
        ):
            self.enterContext(patch.object(execution, name, value))
        self.repin(self.manifest)
        # Imports use the workflow's selected profile. Keep both selections
        # inside this temporary source fixture without clearing the environment.
        v2_path = self.profiles / execution.MANIFEST_NAME_V2
        v2_path.write_text(
            json.dumps(dict(self.manifest, profile=execution.PROFILE_V2))
        )
        for name, value in (
            ("CHAIN_COMMIT_V2", head),
            ("MANIFEST_SHA256_V2", execution.digest(v2_path.read_bytes())),
        ):
            self.enterContext(patch.object(execution, name, value))

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-C", str(self.chain), *args], text=True, stderr=subprocess.PIPE
        )

    def commit(self):
        self.git(
            "-c",
            "user.name=Controlled source fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--quiet",
            "-m",
            "controlled source fixture",
        )

    def repin(self, value):
        self.manifest_path.write_text(json.dumps(value))
        self.enterContext(
            patch.object(
                execution,
                "MANIFEST_SHA256",
                execution.digest(self.manifest_path.read_bytes()),
            )
        )

    def test_exact_source_retains_historical_identity_and_no_authority(self):
        observed = execution.verify(self.chain, execution.PROFILE)
        self.assertEqual(observed["chain_commit"], self.manifest["chain_commit"])
        self.assertEqual(
            observed["historical_profile_sha256"],
            execution.digest(self.profile.read_bytes()),
        )
        self.assertEqual(
            observed["historical_sources_sha256"],
            execution.digest(self.historical.read_bytes()),
        )
        self.assertEqual(
            [
                observed[key]
                for key in (
                    "model_compatibility_changed",
                    "product_qualification",
                    "installation_authorized",
                )
            ],
            [False, False, False],
        )

    def test_unpublishable_sentinel_and_unknown_profile_refuse(self):
        with patch.object(
            execution, "CHAIN_COMMIT", "UNPUBLISHABLE_PENDING_FINAL_CHAIN_SHA"
        ):
            with self.assertRaisesRegex(ValueError, "not been frozen"):
                execution.verify(self.chain, execution.PROFILE)
        with self.assertRaisesRegex(ValueError, "closed execution-source profile"):
            execution.verify(self.chain, "arbitrary-profile")

    def test_relabelled_old_source_cannot_become_the_selected_commit(self):
        value = dict(self.manifest, chain_commit="a" * 40)
        self.repin(value)
        with self.assertRaisesRegex(ValueError, "exact execution-source identity"):
            execution.verify(self.chain, execution.PROFILE)
        with patch.object(execution, "CHAIN_COMMIT", "a" * 40):
            with self.assertRaisesRegex(ValueError, "exact integrated Chain commit"):
                execution.verify(self.chain, execution.PROFILE)

    def test_tracked_and_untracked_source_edits_refuse(self):
        original = self.source.read_bytes()
        self.source.write_bytes(b"fixture_source = False\n")
        with self.assertRaises(subprocess.CalledProcessError):
            execution.verify(self.chain, execution.PROFILE)
        self.source.write_bytes(original)
        (self.chain / "scripts/unreviewed.py").write_text("unreviewed = True\n")
        with self.assertRaisesRegex(ValueError, "untracked inputs"):
            execution.verify(self.chain, execution.PROFILE)

    def test_new_commit_does_not_inherit_old_source_bytes(self):
        self.source.write_bytes(b"fixture_source = None\n")
        self.git("add", "scripts")
        self.commit()
        head = self.git("rev-parse", "HEAD").strip()
        self.repin(dict(self.manifest, chain_commit=head))
        with patch.object(execution, "CHAIN_COMMIT", head):
            with self.assertRaisesRegex(ValueError, "execution source bytes changed"):
                execution.verify(self.chain, execution.PROFILE)

    def test_manifest_tamper_and_changed_historical_identity_refuse(self):
        self.manifest_path.write_text(json.dumps(self.manifest) + " ")
        with self.assertRaisesRegex(ValueError, "exact execution-source manifest"):
            execution.verify(self.chain, execution.PROFILE)
        for field, changed in (
            ("profile", "different-profile"),
            ("schema", "different-schema"),
            ("historical_profile_sha256", "b" * 64),
            ("historical_sources_sha256", "c" * 64),
            ("extra", True),
        ):
            with self.subTest(field=field):
                self.repin(dict(self.manifest, **{field: changed}))
                with self.assertRaises(ValueError):
                    execution.verify(self.chain, execution.PROFILE)
        self.repin(self.manifest)
        self.profile.write_bytes(b"replacement model compatibility\n")
        with self.assertRaisesRegex(ValueError, "must remain unchanged"):
            execution.verify(self.chain, execution.PROFILE)

    def test_missing_original_dependency_and_symlink_source_refuse(self):
        value = copy.deepcopy(self.manifest)
        value["files"] = {
            "scripts/other.py": self.manifest["files"]["scripts/controlled.py"]
        }
        self.repin(value)
        with self.assertRaisesRegex(ValueError, "complete original source closure"):
            execution.verify(self.chain, execution.PROFILE)
        original = self.source.read_bytes()
        self.source.unlink()
        outside = self.chain.parent / "outside.py"
        outside.write_bytes(original)
        self.source.symlink_to(outside)
        self.git("add", "scripts")
        self.commit()
        head = self.git("rev-parse", "HEAD").strip()
        self.repin(dict(self.manifest, chain_commit=head))
        with patch.object(execution, "CHAIN_COMMIT", head):
            with self.assertRaisesRegex(ValueError, "size or path changed"):
                execution.verify(self.chain, execution.PROFILE)

    def test_default_material_source_guard_still_refuses_before_output(self):
        output = self.chain.parent / "not-created"
        with patch.object(material, "PROFILES", self.profiles):
            with self.assertRaisesRegex(
                ValueError, "source differs from the public V2 profile"
            ):
                material.derive(self.chain, self.chain.parent, output, False)
        self.assertFalse(output.exists())

    def import_consumers(self, roles, profile, fixture=None):
        environment = dict(os.environ)
        environment.pop("HEPTA_PAIRED_EXECUTION_PROFILE", None)
        if profile is not None:
            environment["HEPTA_PAIRED_EXECUTION_PROFILE"] = profile
        script = """
import importlib, json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
fixture = json.loads(sys.argv[3])
if fixture is not None:
    import hepta_smollm_execution_source_v1 as execution
    for name, value in fixture.items():
        setattr(execution, name, Path(value) if name == "PROFILES" else value)
roles = json.loads(sys.argv[2])
actual = {}
for name, fields in roles.items():
    module = importlib.import_module(name)
    actual[name] = {field: getattr(module, field) for field in fields}
assert not any(name.startswith("llm_") for name in sys.modules)
print(json.dumps(actual, sort_keys=True))
"""
        return subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                "-c",
                script,
                str(Path(__file__).resolve().parent),
                json.dumps(roles),
                json.dumps(fixture),
            ],
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_all_six_default_consumers_preserve_their_original_source_guards(self):
        result = self.import_consumers(LEGACY_ROLES, None)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), LEGACY_ROLES)

    def test_all_six_consumers_refuse_unknown_profile_before_chain_import(self):
        for name, fields in LEGACY_ROLES.items():
            with self.subTest(consumer=name):
                result = self.import_consumers({name: fields}, "arbitrary-profile")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("closed execution-source profile", result.stderr)

    def fixture_pins(self):
        return {
            "PROFILES": str(self.profiles),
            "CHAIN_COMMIT": execution.CHAIN_COMMIT,
            "MANIFEST_SHA256": execution.MANIFEST_SHA256,
            "HISTORICAL_PROFILE_SHA256": execution.HISTORICAL_PROFILE_SHA256,
            "HISTORICAL_SOURCES_SHA256": execution.HISTORICAL_SOURCES_SHA256,
        }

    def test_all_six_selected_consumers_bind_one_frozen_manifest_identity(self):
        fixture = self.fixture_pins()
        result = self.import_consumers(LEGACY_ROLES, execution.PROFILE, fixture)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            {
                name: dict.fromkeys(fields, self.manifest["chain_commit"])
                for name, fields in LEGACY_ROLES.items()
            },
        )
        self.manifest_path.write_bytes(self.manifest_path.read_bytes() + b" ")
        result = self.import_consumers(LEGACY_ROLES, execution.PROFILE, fixture)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exact execution-source manifest", result.stderr)

    def test_environment_git_selector_cannot_attest_a_different_checkout(self):
        other = self.chain.parent / "different-checkout"
        (other / "scripts").mkdir(parents=True)
        (other / "scripts/controlled.py").write_bytes(self.source.read_bytes())
        for args in (
            ("init", "--quiet"),
            ("add", "scripts"),
            (
                "-c",
                "user.name=Controlled source fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "--quiet",
                "-m",
                "different source identity",
            ),
        ):
            subprocess.run(
                ["git", "-C", str(other), *args], check=True, capture_output=True
            )
        actual = subprocess.check_output(
            ["git", "-C", str(other), "rev-parse", "HEAD"], text=True
        ).strip()
        self.assertNotEqual(actual, execution.CHAIN_COMMIT)
        environment = dict(
            os.environ, GIT_DIR=str(self.chain / ".git"), GIT_WORK_TREE=str(self.chain)
        )
        script = """
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import hepta_smollm_execution_source_v1 as execution
for name, value in json.loads(sys.argv[2]).items():
    setattr(execution, name, Path(value) if name == "PROFILES" else value)
execution.verify(Path(sys.argv[3]), execution.PROFILE)
"""
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                "-c",
                script,
                str(Path(__file__).resolve().parent),
                json.dumps(self.fixture_pins()),
                str(other),
            ],
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertNotEqual(result.returncode, 0, "foreign Git identity was accepted")
        self.assertIn("exact integrated Chain commit", result.stderr)

    def forward_input(self, forward, commit):
        value = dict.fromkeys(
            "schema source_sha256 chain chain_commit sources materials parent "
            "worker_plan tasks output owner_pid deadline_monotonic_ns budget "
            "phase_id model window_id".split()
        )
        value.update(
            schema=forward.SCHEMA,
            source_sha256=execution.digest(Path(forward.__file__).read_bytes()),
            chain=str(self.chain),
            chain_commit=commit,
            sources={},
            materials=str(self.chain.parent),
            budget=dict(wall_seconds=600, rss_bytes=8 * 1024**3),
            deadline_monotonic_ns=time.monotonic_ns() + 10**9,
        )
        path = self.chain.parent / "controlled-forward-input.json"
        path.write_text(json.dumps(value))
        return SimpleNamespace(
            input=str(path), input_sha256=execution.digest(path.read_bytes())
        )

    def test_original_forward_receipt_cannot_be_relabelled_to_new_source(self):
        forward = importlib.import_module("hepta_neural_forward_v1")
        args = self.forward_input(
            forward, LEGACY_ROLES["hepta_neural_forward_v1"]["CHAIN"]
        )
        with (
            patch.object(forward, "CHAIN", execution.CHAIN_COMMIT),
            patch.object(forward, "EXECUTION_SOURCE_PROFILE", execution.PROFILE),
            patch.object(forward, "arm_parent") as parent,
            patch.object(forward.importlib, "import_module") as importer,
        ):
            with self.assertRaisesRegex(
                ValueError, "original source and whole-phase budget"
            ):
                forward.run(args)
            parent.assert_not_called()
            importer.assert_not_called()

    def test_actual_forward_refuses_source_drift_before_worker_import(self):
        forward = importlib.import_module("hepta_neural_forward_v1")
        args = self.forward_input(forward, execution.CHAIN_COMMIT)
        self.source.write_bytes(b"unreviewed = True\n")
        with (
            patch.object(forward, "CHAIN", execution.CHAIN_COMMIT),
            patch.object(forward, "EXECUTION_SOURCE_PROFILE", execution.PROFILE),
            patch.object(forward, "arm_parent"),
            patch.object(forward, "birth"),
            patch.object(forward.importlib, "import_module") as importer,
        ):
            with self.assertRaises(subprocess.CalledProcessError):
                forward.run(args)
            importer.assert_not_called()

    def freeze_fixture(self):
        observation = importlib.import_module("hepta_smollm_observed_execution_v1")
        output = self.chain.parent / "observation-output"
        output.mkdir()
        args = SimpleNamespace(
            parent=self.chain.parent / "parent.json",
            parent_sha256="a" * 64,
            output=output,
        )
        runtime = SimpleNamespace(
            save=lambda path, value: path.write_text(json.dumps(value)),
            file_sha=lambda path: execution.digest(Path(path).read_bytes()),
        )
        parent_step = SimpleNamespace(sources=lambda profile: {"fixture": profile})
        parent = dict(contract="contract", adapter="adapter", file_sha256="b" * 64)
        modules = {
            "llm_initial_trainable_setup_v2": SimpleNamespace(RECIPE={"fixture": True}),
            "llm_runtime_observed_execution_v1": SimpleNamespace(
                PROFILE="controlled-observer", plan_record=lambda value: value
            ),
        }
        return observation, args, runtime, parent_step, parent, modules

    def test_original_freeze_plan_call_without_chain_keeps_legacy_behavior(self):
        observation, args, runtime, parent_step, parent, modules = self.freeze_fixture()
        with (
            patch.object(observation, "EXECUTION_SOURCE_PROFILE", None),
            patch.dict(sys.modules, modules),
        ):
            result = observation.freeze_plan(
                args, runtime, parent_step, parent, self.profile
            )
        path = args.output / "observation-plan-v1.json"
        self.assertEqual(
            result,
            dict(
                files=dict(plan=str(self.profile)),
                parent=parent,
                source={"fixture": "controlled-observer"},
                initial_setup=dict(
                    recipe={"fixture": True},
                    parent_material=dict(path=str(args.parent), sha256="a" * 64),
                    observation_plan=dict(
                        path=str(path), sha256=execution.digest(path.read_bytes())
                    ),
                ),
            ),
        )

    def test_selected_freeze_plan_checks_actual_chain_before_writing_plan(self):
        observation, args, runtime, parent_step, parent, modules = self.freeze_fixture()
        args.chain = self.chain
        with (
            patch.object(observation, "EXECUTION_SOURCE_PROFILE", execution.PROFILE),
            patch.dict(sys.modules, modules),
        ):
            observation.freeze_plan(args, runtime, parent_step, parent, self.profile)
            args.output = self.chain.parent / "refused-observation-output"
            args.output.mkdir()
            self.source.write_bytes(b"unreviewed = True\n")
            with self.assertRaises(subprocess.CalledProcessError):
                observation.freeze_plan(
                    args, runtime, parent_step, parent, self.profile
                )
            self.assertEqual(list(args.output.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
