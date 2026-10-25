"""Small fixtures only: never scan real task evidence while timing is active."""

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import evidence_inventory as inventory


class EvidenceInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hepta-inventory-fixture-")
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name)
        self.addCleanup(patch.stopall)
        patch.object(inventory, "TASK_WORKSPACE", self.workspace).start()
        for name in inventory.TASK_DIRECTORY_NAMES:
            (self.workspace / name).mkdir()
        self.expected = {
            "abc2-runs/run-a/failure.json": b'{"failed":true}\n',
            "abc2-runs/run-a/raw-media.zip": b"raw fixture bytes",
            "abc2-runs/run-a/checkpoints/step-100.pt": b"checkpoint",
            "abc2-runs/run-b/weights.pt": b"weights",
            "abc2-assets/source.bin": b"source",
            "runtime-receipts/cost.json": b"{}\n",
        }
        for name, value in self.expected.items():
            path = self.workspace / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(value)
        (self.workspace / "abc2-runs/empty-run").mkdir()
        self.output = self.workspace / "inventory.json"

    def test_complete_census_hashes_summaries_and_no_overwrite(self):
        receipt = inventory.write_inventory(self.output)
        result = json.loads(self.output.read_bytes())
        self.assertEqual(result["files"], [
            {"relative_path": name, "size_bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()}
            for name, value in sorted(self.expected.items())])
        self.assertEqual(result["by_run"], {
            "abc2-runs/empty-run": {"file_count": 0, "total_bytes": 0},
            "abc2-runs/run-a": {"file_count": 3, "total_bytes": sum(len(self.expected[name]) for name in self.expected if "/run-a/" in name)},
            "abc2-runs/run-b": {"file_count": 1, "total_bytes": len(b"weights")}})
        self.assertEqual((result["file_count"], result["total_bytes"]), (6, sum(map(len, self.expected.values()))))
        self.assertEqual(receipt["sha256"], hashlib.sha256(self.output.read_bytes()).hexdigest())
        with self.assertRaisesRegex(inventory.InventoryError, "already exists"):
            inventory.write_inventory(self.output)
        self.assertEqual({name: (self.workspace / name).read_bytes() for name in self.expected}, self.expected)

    def test_escape_and_internal_symlinks_are_refused(self):
        outside = self.workspace / "outside.txt"
        outside.write_bytes(b"must not be opened through a task symlink")
        link = self.workspace / "abc2-runs/run-a/escape"
        for target in (outside, self.workspace / "abc2-assets"):
            link.symlink_to(target)
            with self.assertRaisesRegex(inventory.InventoryError, "Symbolic link refused"):
                inventory.write_inventory(self.output)
            self.assertFalse(self.output.exists())
            link.unlink()
        (self.workspace / "runtime-receipts").rename(self.workspace / "moved-receipts")
        (self.workspace / "runtime-receipts").symlink_to(self.workspace / "moved-receipts")
        with self.assertRaises(OSError):
            inventory.write_inventory(self.output)

    def test_file_and_census_changes_are_refused(self):
        original = inventory._hash_file
        mutated = False

        def mutate_after_read(workspace, name, expected):
            nonlocal mutated
            value = original(workspace, name, expected)
            if not mutated:
                mutated = True
                (self.workspace / name).write_bytes(b"changed after its SHA was computed")
            return value

        with patch.object(inventory, "_hash_file", mutate_after_read):
            with self.assertRaisesRegex(inventory.InventoryError, "changed during inventory"):
                inventory.write_inventory(self.output)
        self.assertFalse(self.output.exists())

        def add_after_read(workspace, name, expected):
            value = original(workspace, name, expected)
            (self.workspace / "runtime-receipts/new-file").touch(exist_ok=True)
            return value

        with patch.object(inventory, "_hash_file", add_after_read):
            with self.assertRaisesRegex(inventory.InventoryError, "changed"):
                inventory.write_inventory(self.output)
        self.assertFalse(self.output.exists())

    def test_special_entries_and_output_inside_evidence_are_refused(self):
        with self.assertRaisesRegex(inventory.InventoryError, "outside the three scan roots"):
            inventory.write_inventory(self.workspace / "abc2-runs/manifest.json")
        os.mkfifo(self.workspace / "abc2-assets/not-a-regular-file")
        with self.assertRaisesRegex(inventory.InventoryError, "Non-regular evidence entry"):
            inventory.write_inventory(self.output)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
