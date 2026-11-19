"""Offline packaging controls; these synthetic bytes do not qualify the renderer."""

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "tools" / "group-robrix-evidence.py"
spec = importlib.util.spec_from_file_location("group_robrix_evidence", path)
grouping = importlib.util.module_from_spec(spec)
spec.loader.exec_module(grouping)


class EvidencePartitionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.paths = [
            "test-results/robrix-fixtures/robrix-host-case-webkit/original.png",
            "test-results/robrix-fixtures/robrix-sidebar-case-webkit/sidebar-evidence.json",
            "test-results/robrix-fixtures/robrix-sidebar-case-firefox/after-one-new-draft.png",
            "test-results/robrix-fixtures/robrix-sidebar-case-chromium/closed-sidebar-Enter.png",
            "test-results/robrix-default/robrix-host-case-chromium/original.png",
            "test-results/robrix-fixtures/.last-run.json",
            "test-results/robrix-fixtures-results.json",
            "dist-robrix-fixtures/build-manifest.json",
        ]
        for index, name in enumerate(self.paths):
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(f"synthetic evidence {index}".encode())
        self.sources = grouping.collect_sources(self.root)
        self.entries = [(source, grouping.group_for_path(source.relative_to(self.root))) for source in self.sources]

    def tearDown(self):
        self.directory.cleanup()

    def test_preserves_every_source_byte_path_and_hash_once(self):
        inventory = grouping.write_groups(self.root, "a" * 40, self.sources, self.entries)
        self.assertEqual(set(self.paths), {item["path"] for item in inventory})
        summary = json.loads((self.root / "test-results/evidence-groups/summary/evidence-manifest.json").read_text())
        self.assertEqual(summary["files"], inventory)
        self.assertFalse(summary["qualification"])
        for item in inventory:
            original = (self.root / item["path"]).read_bytes()
            saved = (self.root / "test-results/evidence-groups" / item["group"] / item["path"]).read_bytes()
            self.assertEqual(saved, original)
            self.assertEqual(item["sha256"], hashlib.sha256(saved).hexdigest())
        self.assertEqual(grouping.group_for_path(Path(self.paths[0])), "fixtures-webkit")
        self.assertEqual(grouping.group_for_path(Path(self.paths[1])), "sidebar-webkit")

    def test_omitted_source_fails(self):
        with self.assertRaisesRegex(ValueError, "omits"):
            grouping.validate_partition(self.root, self.sources, self.entries[:-1])

    def test_duplicate_source_fails(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            grouping.validate_partition(self.root, self.sources, self.entries + self.entries[:1])

    def test_wrong_browser_classification_fails(self):
        entries = list(self.entries)
        index = next(i for i, (_, group) in enumerate(entries) if group == "sidebar-webkit")
        entries[index] = (entries[index][0], "sidebar-firefox")
        with self.assertRaisesRegex(ValueError, "classification"):
            grouping.validate_partition(self.root, self.sources, entries)

    def test_unrecognized_browser_or_nonfixture_sidebar_fails(self):
        for name in ["test-results/robrix-fixtures/robrix-sidebar-case-unknown/file.png", "test-results/robrix-default/robrix-sidebar-case-webkit/file.png"]:
            with self.assertRaises(ValueError):
                grouping.group_for_path(Path(name))


if __name__ == "__main__":
    unittest.main()
