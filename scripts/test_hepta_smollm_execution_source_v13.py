"""V13 mechanisms use isolated Git fixtures; no native or model qualification."""

import copy
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import hepta_smollm_execution_source_v1 as execution

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "codex-rs/hepta-learning-artifacts/profiles"
COMMIT = "5bb29d6ae39fa0c71f9151f3dce31fa1a3ab1800"
TREE = "2ca582833816507e9102378610b4db2228a7395a"


class FrozenProfileControls(unittest.TestCase):
    def test_v13_is_a_distinct_complete_tuple_and_v12_bytes_remain_frozen(self):
        old = execution.checked_manifest(execution.PROFILE_V12)
        current = execution.checked_manifest(execution.PROFILE_V13)
        self.assertEqual(
            (current["chain_commit"], current["chain_tree"]), (COMMIT, TREE)
        )
        self.assertEqual(len(current["files"]), 53)
        self.assertEqual(set(current["files"]), set(old["files"]))
        changed = [
            p for p in current["files"] if current["files"][p] != old["files"][p]
        ]
        self.assertEqual(
            changed,
            [
                "config/pon/pq-cross-branch-corpus-v1.json",
                "scripts/llm_runtime_release.py",
            ],
        )
        self.assertEqual(
            {path: current["files"][path]["sha256"] for path in changed},
            {
                "config/pon/pq-cross-branch-corpus-v1.json": "4fe0ef0480728fd4922e7c0ed3c45bdab1f42d6eb66a5a27082c93aa95bbdd1b",
                "scripts/llm_runtime_release.py": "b6eb1f411ce430a7da8d860a32fcddc61f6f75d2fd14026120a83744730a4453",
            },
        )
        frozen = {
            "smollm2-public-initial-v2.execution-sources-v12.json": "02b51be8bd41850879993def86533da0b4870dece4c3d7be2afd646497768902",
            "smollm2-neural-forward-v2.sources.json": "2af311dd66043dcaa43701606075511a2a838e84a19ff826ed74fd17d1479fe7",
        }
        for name, expected in frozen.items():
            self.assertEqual(execution.digest((PROFILES / name).read_bytes()), expected)

    def test_v13_and_v12_do_not_inherit_the_legacy_forward(self):
        forward = importlib.import_module("hepta_neural_forward_v1")
        study = importlib.import_module("hepta_neural_study_v1")
        for module, call in (
            (forward, lambda: forward.run(SimpleNamespace())),
            (study, lambda: study.forward({}, None)),
        ):
            with patch.object(
                module, "EXECUTION_SOURCE_PROFILE", execution.PROFILE_V13
            ):
                with self.assertRaisesRegex(
                    ValueError, "explicit runtime-bound forward-v3"
                ):
                    call()
        with self.assertRaisesRegex(ValueError, "explicit runtime-bound forward-v2"):
            execution.require_legacy_worker_profile(execution.PROFILE_V12)
        with self.assertRaisesRegex(ValueError, "legacy worker-v1"):
            execution.require_legacy_worker_profile(execution.PROFILE_V11)


class ExactSourceControls(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.chain = self.root / "chain"
        self.chain.mkdir()
        self.profiles = self.root / "profiles"
        self.profiles.mkdir()
        current = execution.checked_manifest(execution.PROFILE_V13)
        for name in (
            "smollm2-public-initial-v2.profile",
            "smollm2-public-initial-v2.sources.json",
            execution.MANIFEST_NAME_V12,
        ):
            (self.profiles / name).write_bytes((PROFILES / name).read_bytes())
        self.old = {p.name: p.read_bytes() for p in self.profiles.iterdir()}
        files = {}
        for relative in current["files"]:
            path = self.chain / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            raw = ("non-executed source fixture: " + relative + "\n").encode()
            path.write_bytes(raw)
            files[relative] = dict(size=len(raw), sha256=execution.digest(raw))
        self.native = self.chain / "trillionnium/crates/component/src/lib.rs"
        self.native.parent.mkdir(parents=True)
        self.native.write_text("pub const COMPONENT_ONLY: u64 = 1;\n")
        (self.chain / ".gitignore").write_text("**/ambient-*\n")
        self.git("init", "-q")
        self.git("add", ".")
        self.git(
            "-c",
            "user.name=Component",
            "-c",
            "user.email=component@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "isolated source fixture",
        )
        self.head = self.git("rev-parse", "HEAD").strip()
        self.tree = self.git("rev-parse", "HEAD^{tree}").strip()
        self.manifest = dict(
            current, chain_commit=self.head, chain_tree=self.tree, files=files
        )
        self.path = self.profiles / execution.MANIFEST_NAME_V13
        self.enterContext(patch.object(execution, "PROFILES", self.profiles))
        self.enterContext(patch.object(execution, "CHAIN_COMMIT_V13", self.head))
        self.enterContext(patch.object(execution, "CHAIN_TREE_V13", self.tree))
        self.enterContext(patch.object(sys, "dont_write_bytecode", True))
        self.enterContext(patch.dict(os.environ, {"PYTHONDONTWRITEBYTECODE": "1"}))
        self.repin(self.manifest)

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.chain), *args], text=True)

    def repin(self, value):
        self.path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")
        self.enterContext(
            patch.object(
                execution,
                "MANIFEST_SHA256_V13",
                execution.digest(self.path.read_bytes()),
            )
        )

    def verify(self):
        return execution.verify(self.chain, execution.PROFILE_V13)

    def test_complete_fixture_keeps_historical_profiles_and_no_authority(self):
        result = self.verify()
        self.assertEqual(result["verified_source_files"], 53)
        self.assertEqual(
            (result["chain_commit"], result["chain_tree"]), (self.head, self.tree)
        )
        self.assertEqual(
            {p.name: p.read_bytes() for p in self.profiles.iterdir() if p != self.path},
            self.old,
        )
        for name in (
            "model_compatibility_changed",
            "product_qualification",
            "installation_authorized",
        ):
            self.assertIs(result[name], False)

    def test_each_omission_or_extra_path_refuses_after_manifest_self_rehash(self):
        for relative in self.manifest["files"]:
            changed = copy.deepcopy(self.manifest)
            del changed["files"][relative]
            self.repin(changed)
            with self.subTest(relative=relative):
                with self.assertRaisesRegex(ValueError, "exact complete 53-source"):
                    self.verify()
        changed = copy.deepcopy(self.manifest)
        changed["files"]["scripts/extra.py"] = dict(size=1, sha256="1" * 64)
        self.repin(changed)
        with self.assertRaisesRegex(ValueError, "exact complete 53-source"):
            self.verify()

    def test_self_rehashed_profile_commit_tree_and_manifest_swaps_refuse(self):
        for field, replacement in (
            ("profile", execution.PROFILE_V12),
            ("chain_commit", execution.CHAIN_COMMIT_V12),
            ("chain_tree", execution.CHAIN_TREE_V12),
        ):
            changed = dict(self.manifest, **{field: replacement})
            self.repin(changed)
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.verify()
        self.repin(
            json.loads((self.profiles / execution.MANIFEST_NAME_V12).read_bytes())
        )
        with self.assertRaises(ValueError):
            self.verify()

    def test_native_lock_and_source_drift_are_not_hidden_by_the_profile(self):
        for path in (
            self.native,
            self.chain / "trillionnium/Cargo.lock",
            self.chain / "scripts/llm_neural_read_worker.py",
        ):
            original = path.read_bytes()
            path.write_bytes(original + b"unreviewed change\n")
            try:
                with self.subTest(path=path):
                    with self.assertRaisesRegex(
                        ValueError, "candidate checkout is dirty"
                    ):
                        self.verify()
            finally:
                path.write_bytes(original)

    def test_hidden_ignored_and_inherited_bytecode_changes_remain_refused(self):
        relative = "scripts/llm_python_runtime_contract.py"
        self.git("update-index", "--assume-unchanged", relative)
        try:
            with self.assertRaisesRegex(ValueError, "hidden index"):
                self.verify()
        finally:
            self.git("update-index", "--no-assume-unchanged", relative)
        extra = self.chain / "scripts/ambient-shadow.py"
        extra.write_text("not admitted\n")
        try:
            with self.assertRaisesRegex(ValueError, "ignored inputs"):
                self.verify()
        finally:
            extra.unlink()
        with patch.dict(os.environ, {"PYTHONDONTWRITEBYTECODE": "0"}):
            with self.assertRaisesRegex(ValueError, "V13 requires disabled bytecode"):
                self.verify()


if __name__ == "__main__":
    unittest.main()
