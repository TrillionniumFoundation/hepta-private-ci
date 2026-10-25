"""Actual filesystem aliases and the quality gate, without model imports."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import storage_ledger
from storage_ledger import compression_gain, deployment, inventory


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def component(self, name, kind, content):
        path = self.root / name
        path.write_bytes(content)
        return {"name": name, "kind": kind, "paths": [str(path)]}

    def test_hardlinks_and_identical_copies_are_distinct(self):
        a = self.component("a", "base", b"same content")
        b = self.component("b", "adapter", b"same content")
        os.link(self.root / "a", self.root / "link")
        c = {"name": "c", "kind": "source", "paths": [str(self.root / "link")]}
        measured = inventory([a, b, c])
        totals = measured["totals"]
        self.assertEqual(
            {
                k: totals[k]
                for k in (
                    "file_entries",
                    "physical_files",
                    "logical_file_bytes",
                    "physical_payload_bytes",
                    "content_unique_bytes",
                    "hardlink_repeated_path_bytes",
                    "content_duplicate_inode_bytes",
                )
            },
            dict(
                file_entries=3,
                physical_files=2,
                logical_file_bytes=36,
                physical_payload_bytes=24,
                content_unique_bytes=12,
                hardlink_repeated_path_bytes=12,
                content_duplicate_inode_bytes=12,
            ),
        )
        self.assertEqual(measured["inventory_measurement"]["hash_read_bytes"], 24)

    def test_retrieval_does_not_pay_for_unused_base(self):
        measured = inventory(
            [
                self.component("source", "source", b"abc"),
                self.component("base", "base", b"0123456789"),
            ]
        )
        placements = [
            {"host": "one", "consumer": "memory", "components": ["source", "base"]},
            {"host": "one", "consumer": "retrieval", "components": ["source"]},
        ]
        self.assertEqual(
            deployment(measured, placements)["totals"]["logical_file_bytes"], 13
        )
        placements[1]["host"] = "two"
        self.assertEqual(
            deployment(measured, placements)["totals"]["logical_file_bytes"], 16
        )
        self.assertEqual(
            deployment(measured, placements[1:])["totals"]["logical_file_bytes"], 3
        )

    def test_overlap_and_symlink_are_refused(self):
        item = self.component("source", "source", b"x")
        with self.assertRaises(ValueError):
            inventory([item, dict(item, name="duplicate")])
        folder = self.root / "folder"
        folder.mkdir()
        (folder / "link").symlink_to(self.root / "source")
        with self.assertRaises(ValueError):
            inventory([{"name": "links", "kind": "source", "paths": [str(folder)]}])

    def test_late_mutation_cannot_replace_the_hashed_metadata_stamp(self):
        item = self.component("changing", "source", b"old")
        original = storage_ledger.file_record

        def late_mutation(path, cache):
            result = original(path, cache)
            path.write_bytes(b"new bytes after hash")
            return result

        with patch.object(storage_ledger, "file_record", late_mutation):
            with self.assertRaisesRegex(ValueError, "metadata changed"):
                inventory([item])

    def test_no_quality_no_gain_and_failed_pairs_never_disappear(self):
        gate = {
            "scope": "independent-future-tasks",
            "minimum_groups": 1,
            "complete_cost_closure": True,
            "rows": [],
        }
        self.assertIsNone(
            compression_gain(1, 2, gate)["net_storage_reduction_fraction"]
        )
        row = {
            "task_id": "a",
            "group_id": "g",
            "memory_supported": True,
            "memory_passed": True,
            "retrieval_supported": True,
            "retrieval_passed": True,
        }
        gate["rows"] = [row]
        self.assertEqual(
            compression_gain(1, 2, gate)["net_storage_reduction_fraction"], 0.5
        )
        gate["rows"] = [dict(row, memory_passed=False)]
        self.assertIsNone(
            compression_gain(1, 2, gate)["net_storage_reduction_fraction"]
        )
        gate["rows"] = [row, dict(row, task_id="repeat")]
        gate["minimum_groups"] = 2
        self.assertEqual(compression_gain(1, 2, gate)["independent_groups"], 1)
        self.assertIsNone(
            compression_gain(1, 2, gate)["net_storage_reduction_fraction"]
        )
        gate["minimum_groups"], gate["complete_cost_closure"] = 1, False
        self.assertIsNone(
            compression_gain(1, 2, gate)["net_storage_reduction_fraction"]
        )


if __name__ == "__main__":
    unittest.main()
