import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts import hepta_memory_retrieval_refresh_map as refresh


class MapRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Map test fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.write(refresh.ROOT + "/src/lib.rs", "// fixture\n")
        self.original = {"module": "memory.retrieval", "sourceBase": {"commit": "0" * 40},
                         "claimBoundary": {"productionImplementation": False, "activation": False},
                         "operations": [{"operation": "retrieve"}], "observedSourcePaths": []}
        self.write(refresh.MAP, json.dumps(self.original))
        self.commit()

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def commit(self):
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")
        self.head = self.git("rev-parse", "HEAD")

    def test_binds_exact_objects_and_preserves_provenance_claims_and_operations(self):
        mapping = refresh.refresh(self.root, self.head)
        self.assertEqual(mapping["observedAtHead"], {"commit": self.head, "tree": self.git("rev-parse", "HEAD^{tree}")})
        for name in ("sourceBase", "claimBoundary", "operations"):
            self.assertEqual(mapping[name], self.original[name])
        self.assertEqual({row["path"]: row["object"] for row in mapping["sourceObjects"]}[refresh.ROOT],
                         self.git("rev-parse", "HEAD:" + refresh.ROOT))
        self.assertTrue(set(refresh.INPUTS).issubset(mapping["observedSourcePaths"]))

    def test_map_and_parent_trees_are_not_self_referential_objects(self):
        mapping = refresh.refresh(self.root, self.head)
        for row in mapping["sourceObjects"]:
            self.assertNotEqual(row["path"], refresh.MAP)
            self.assertFalse(refresh.MAP.startswith(row["path"] + "/"))

    def test_untracked_file_invalidates_clean_source(self):
        self.write("untracked.txt", "work in progress")
        with self.assertRaises(refresh.RefreshError):
            refresh.refresh(self.root, self.head)

    def test_modified_source_invalidates_clean_source(self):
        self.write(refresh.ROOT + "/src/lib.rs", "// changed\n")
        with self.assertRaises(refresh.RefreshError):
            refresh.refresh(self.root, self.head)

    def test_another_head_is_rejected(self):
        with self.assertRaises(refresh.RefreshError):
            refresh.refresh(self.root, "a" * 40)

    def test_unsafe_inherited_path_is_rejected(self):
        self.original["observedSourcePaths"] = ["../escape"]
        self.write(refresh.MAP, json.dumps(self.original))
        self.commit()
        with self.assertRaises(refresh.RefreshError):
            refresh.refresh(self.root, self.head)

    def test_wrong_module_is_rejected(self):
        self.original["module"] = "another.module"
        self.write(refresh.MAP, json.dumps(self.original))
        self.commit()
        with self.assertRaises(refresh.RefreshError):
            refresh.refresh(self.root, self.head)

    def test_missing_paths_are_explicit_without_fabricated_objects(self):
        mapping = refresh.refresh(self.root, self.head)
        self.assertIn("codex-rs/Cargo.lock", mapping["observedMissingPaths"])
        self.assertNotIn("codex-rs/Cargo.lock", {row["path"] for row in mapping["sourceObjects"]})


if __name__ == "__main__":
    unittest.main()
