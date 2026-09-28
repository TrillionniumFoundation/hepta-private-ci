from __future__ import annotations

import copy
from pathlib import Path
import subprocess
import tempfile
import unittest

import hepta_artifact_source_binding as binding


class BindingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.run_git("init", "-q")
        self.path = binding.SOURCE_ROOT + "/src/example.rs"
        (self.root / self.path).parent.mkdir(parents=True)
        (self.root / self.path).write_text("pub fn example() {}\n")
        self.run_git("add", ".")
        self.tree = self.run_git("write-tree")
        self.mapping = {
            "module": "learning.artifacts", "sourceBase": {"commit": "historical", "tree": "historical"},
            "claimBoundary": {"productionImplementation": False, "activation": False},
            "operations": [{"operation": "example", "sourcePath": self.path, "sourceBlob": "stale",
                            "tests": [], "state": "qualification_pending"}],
            "sourceObjects": [{"path": self.path, "object": "stale"}],
            "repositoryControlledGaps": ["native execution remains pending"],
        }

    def run_git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root, text=True).strip()

    def test_refresh_preserves_provenance_pending_state_and_input(self):
        original = copy.deepcopy(self.mapping)
        result = binding.refreshed(self.root, self.tree, self.mapping, [])
        self.assertEqual(self.mapping, original)
        for key in ("sourceBase", "claimBoundary", "repositoryControlledGaps"):
            self.assertEqual(result[key], original[key])
        self.assertEqual(result["operations"][0]["state"], "qualification_pending")
        self.assertEqual(result["operations"][0]["tests"], [])
        self.assertEqual(result["operations"][0]["sourceBlob"], self.run_git("rev-parse", f"{self.tree}:{self.path}"))
        self.assertIn(binding.SOURCE_ROOT, {entry["path"] for entry in result["sourceObjects"]})

    def test_only_named_tree_not_unstaged_bytes_is_sealed(self):
        original = binding.refreshed(self.root, self.tree, self.mapping, [])
        (self.root / self.path).write_text("pub fn changed() {}\n")
        self.assertEqual(binding.refreshed(self.root, self.tree, self.mapping, []), original)
        self.run_git("add", ".")
        updated = binding.refreshed(self.root, self.run_git("write-tree"), self.mapping, [])
        self.assertNotEqual(updated["operations"][0]["sourceBlob"], original["operations"][0]["sourceBlob"])

    def test_check_is_idempotent(self):
        first = binding.refreshed(self.root, self.tree, self.mapping, [])
        self.assertEqual(binding.refreshed(self.root, self.tree, first, []), first)

    def test_duplicate_objects_and_operations_fail(self):
        for key in ("sourceObjects", "operations"):
            value = copy.deepcopy(self.mapping)
            value[key].append(copy.deepcopy(value[key][0]))
            with self.assertRaises(binding.BindingError):
                binding.refreshed(self.root, self.tree, value, [])

    def test_self_referential_and_escaping_paths_fail(self):
        for path in (binding.MAP, "../escape", "/absolute", "a/../b", "a//b", "a\\b", "./x", "x\ny"):
            with self.subTest(path=path), self.assertRaises(binding.BindingError):
                binding.refreshed(self.root, self.tree, self.mapping, [path])

    def test_abbreviated_tree_is_not_an_exact_identity(self):
        with self.assertRaises(binding.BindingError):
            binding.refreshed(self.root, self.tree[:12], self.mapping, [])

    def test_operation_cannot_bind_directory(self):
        value = copy.deepcopy(self.mapping)
        value["operations"][0]["sourcePath"] = binding.SOURCE_ROOT
        with self.assertRaises(binding.BindingError):
            binding.refreshed(self.root, self.tree, value, [])


if __name__ == "__main__":
    unittest.main()
