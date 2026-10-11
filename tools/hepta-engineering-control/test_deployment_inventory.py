"""Executable ownership and exact-source counterexamples, no activation claims."""
import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from deployment_inventory import InventoryError, build_mapping, duplicate_keys, inventory


class MappingTests(unittest.TestCase):
    def setUp(self):
        self.modules = [{"id": "store", "owner": "memory", "deputy": "durability",
                         "rootBindings": [{"path": "crates/store", "mode": "exclusive"}]},
                        {"id": "host", "owner": "runtime", "deputy": "security",
                         "rootBindings": [{"path": "crates/host", "mode": "exclusive"}]}]
        self.organs = [{"id": "memory", "moduleBindings": ["store"],
                        "dependencies": [], "fallbackOrgans": []}]
        self.domains = [{"id": "facts", "schemaOwner": "store",
                         "authoritativeWriter": "store", "readers": ["host"]}]
        self.files = {"crates/store/Cargo.toml": {"mode": "100644", "sha": "1" * 40,
                                                 "package": "store"}}

    def project(self):
        return build_mapping(self.modules, self.organs, self.domains, self.files)

    def test_source_is_not_deployment(self):
        result = self.project()
        row = next(m for m in result["modules"] if m["id"] == "store")
        self.assertEqual(row["writerDomains"], ["facts"])
        self.assertEqual(row["organs"], ["memory"])
        self.assertIsNone(row["hostBinding"])
        self.assertFalse(row["productionCallerVerified"])
        self.assertEqual(result["dataDomains"][0]["authoritativeWriter"], "store")

    def test_missing_root_remains_missing(self):
        row = next(m for m in self.project()["modules"] if m["id"] == "host")
        self.assertFalse(row["roots"][0]["ordinarySourcePresent"])

    def test_symlink_is_not_materialized_source(self):
        self.files = {"crates/store": {"mode": "120000", "sha": "1" * 40}}
        row = next(m for m in self.project()["modules"] if m["id"] == "store")
        self.assertFalse(row["roots"][0]["ordinarySourcePresent"])

    def test_unknown_and_duplicate_owners_reject(self):
        for field in ("schemaOwner", "authoritativeWriter"):
            with self.subTest(field=field):
                domains = copy.deepcopy(self.domains)
                domains[0][field] = "ghost"
                with self.assertRaises(InventoryError):
                    build_mapping(self.modules, self.organs, domains, self.files)
        self.domains.append(copy.deepcopy(self.domains[0]))
        with self.assertRaises(InventoryError):
            self.project()

    def test_forbidden_writer_rejects(self):
        self.domains[0]["forbiddenWriters"] = ["store"]
        with self.assertRaises(InventoryError):
            self.project()

    def test_unknown_organ_binding_and_edge_reject(self):
        self.organs[0]["moduleBindings"] = ["ghost"]
        with self.assertRaises(InventoryError):
            self.project()
        self.organs[0]["moduleBindings"] = ["store"]
        self.organs[0]["dependencies"] = ["ghost"]
        with self.assertRaises(InventoryError):
            self.project()

    def test_qualification_is_not_fabricated_module(self):
        self.organs[0]["moduleBindings"].append("hnmf.reference")
        result = self.project()
        self.assertEqual(result["counts"]["modules"], 2)
        binding = result["organs"][0]["qualificationBindings"][0]
        self.assertEqual(binding["scope"], "qualification_only_not_production_module")
        self.assertFalse(binding["sourcePresent"])

    def test_path_escape_and_duplicate_json_reject(self):
        for path in ("../escape", "/absolute", "a/../b", "a//b"):
            self.modules[0]["rootBindings"][0]["path"] = path
            with self.assertRaises(InventoryError):
                self.project()
        with self.assertRaises(InventoryError):
            json.loads('{"a":1,"a":2}', object_pairs_hook=duplicate_keys)

    def test_projection_is_deterministic_and_nonmutating(self):
        before = copy.deepcopy((self.modules, self.organs, self.domains, self.files))
        first = self.project()
        self.modules.reverse()
        self.assertEqual(first, self.project())
        self.modules.reverse()
        self.assertEqual(before, (self.modules, self.organs, self.domains, self.files))

    def test_inventory_uses_committed_bytes_not_dirty_worktree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def run(*args):
                return subprocess.check_output(["git", "-C", tmp, *args], stderr=subprocess.DEVNULL)
            run("init")
            run("config", "user.name", "fixture")
            run("config", "user.email", "fixture@invalid")
            for path, content in {
                "docs/modules/MODULES.json": {"modules": self.modules},
                "docs/cns/CNS_ARCHITECTURE.json": {"organs": self.organs},
                "docs/data/DATA_AUTHORITY.json": {"domains": self.domains},
            }.items():
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(content))
            package = root / "crates/store/Cargo.toml"
            package.parent.mkdir(parents=True)
            package.write_text('[package]\nname = "store"\n')
            run("add", ".")
            run("commit", "-m", "fixture")
            head = run("rev-parse", "HEAD").decode().strip()
            first = inventory(root, head)
            package.write_text("malformed dirty content")
            (root / "docs/data/DATA_AUTHORITY.json").write_text("bad")
            self.assertEqual(first, inventory(root, head))
            with self.assertRaises(InventoryError):
                inventory(root, "main")


if __name__ == "__main__":
    unittest.main()
