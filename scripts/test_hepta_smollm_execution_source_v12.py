"""V12 source admission controls; no model execution or inherited qualification."""

import copy
import importlib
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import hepta_smollm_execution_source_v1 as execution
import test_hepta_smollm_execution_source_v11 as fixtures


class BridgedExecutionSourceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RuntimeBoundExecutionSourceTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.chain = self.fixture.chain
        self.profiles = self.fixture.fixture.profiles
        self.old = {
            p.name: p.read_bytes()
            for p in self.profiles.iterdir()
            if p.name != execution.MANIFEST_NAME_V12
        }
        self.manifest = dict(self.fixture.manifest, profile=execution.PROFILE_V12)
        self.path = self.profiles / execution.MANIFEST_NAME_V12
        self.enterContext(
            patch.object(execution, "CHAIN_COMMIT_V12", self.fixture.head)
        )
        self.enterContext(patch.object(execution, "CHAIN_TREE_V12", self.fixture.tree))
        self.repin(self.manifest)

    def repin(self, manifest):
        import json

        self.path.write_text(json.dumps(manifest))
        self.enterContext(
            patch.object(
                execution,
                "MANIFEST_SHA256_V12",
                execution.digest(self.path.read_bytes()),
            )
        )

    def verify(self):
        return execution.verify(self.chain, execution.PROFILE_V12)

    def test_current_profile_keeps_all_historical_bytes_and_denies_authority(self):
        value = self.verify()
        self.assertEqual(
            (value["chain_commit"], value["chain_tree"]),
            (self.fixture.head, self.fixture.tree),
        )
        self.assertEqual(
            {p.name: p.read_bytes() for p in self.profiles.iterdir() if p != self.path},
            self.old,
        )
        self.assertEqual(
            [
                value[k]
                for k in (
                    "model_compatibility_changed",
                    "product_qualification",
                    "installation_authorized",
                )
            ],
            [False, False, False],
        )

    def test_full_v11_closure_cannot_shrink_after_new_manifest_self_rehash(self):
        for relative in self.manifest["files"]:
            with self.subTest(relative=relative):
                changed = copy.deepcopy(self.manifest)
                del changed["files"][relative]
                self.repin(changed)
                with self.assertRaisesRegex(ValueError, "complete historical V11"):
                    self.verify()
        self.repin(self.manifest)
        self.assertEqual(
            {p.name: p.read_bytes() for p in self.profiles.iterdir() if p != self.path},
            self.old,
        )

    def test_native_runtime_and_hidden_source_drift_remain_refused(self):
        runtime = self.chain / "scripts/llm_python_runtime_contract.py"
        for path in (runtime, self.fixture.native, self.fixture.lockfile):
            with self.subTest(path=path):
                original = path.read_bytes()
                path.write_bytes(original + b"unreviewed bytes\n")
                try:
                    with self.assertRaisesRegex(
                        ValueError, "candidate checkout is dirty"
                    ):
                        self.verify()
                finally:
                    path.write_bytes(original)
        relative = str(runtime.relative_to(self.chain))
        self.fixture.fixture.git("update-index", "--assume-unchanged", relative)
        try:
            with self.assertRaisesRegex(ValueError, "hidden index"):
                self.verify()
        finally:
            self.fixture.fixture.git("update-index", "--no-assume-unchanged", relative)
        self.verify()

    def test_current_profile_never_selects_the_old_forward_implicitly(self):
        forward = importlib.import_module("hepta_neural_forward_v1")
        study = importlib.import_module("hepta_neural_study_v1")
        with patch.object(forward, "EXECUTION_SOURCE_PROFILE", execution.PROFILE_V12):
            with self.assertRaisesRegex(
                ValueError, "explicit runtime-bound forward-v2"
            ):
                forward.run(SimpleNamespace())
        with patch.object(study, "EXECUTION_SOURCE_PROFILE", execution.PROFILE_V12):
            with self.assertRaisesRegex(
                ValueError, "explicit runtime-bound forward-v2"
            ):
                study.forward({}, None)
        with self.assertRaisesRegex(ValueError, "legacy worker-v1"):
            execution.require_legacy_worker_profile(execution.PROFILE_V11)


if __name__ == "__main__":
    unittest.main()
