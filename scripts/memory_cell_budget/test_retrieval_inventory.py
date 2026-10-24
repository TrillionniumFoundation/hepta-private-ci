"""Actual persisted retrieval and full-store accounting, without model imports."""

import hashlib
import os
from pathlib import Path
import tempfile
import unittest

from artifact_inventory import measure
from retrieval_index import Retriever, build


class RetrievalInventoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def documents(self):
        docs = []
        for index, text in enumerate(
            [
                "rustup component add rustfmt; cargo fmt",
                "python -m pip install packaging",
                "rustup component add clippy; cargo clippy",
            ]
        ):
            docs.append(
                dict(
                    doc_id=str(index),
                    group_id=f"group-{index}",
                    path=f"workflow/{index}.yml",
                    text=text,
                    available_at="2026-10-01T00:00:00Z",
                    origin=f"https://example.test/source/{index}",
                    source_sha256=hashlib.sha256(text.encode()).hexdigest(),
                )
            )
        return docs

    def test_reopened_index_executes_content_retrieval_with_source_bindings(self):
        path = self.root / "index.sqlite3"
        receipt = build(path, self.documents(), train_until="2026-10-20T00:00:00Z")
        reader = Retriever(path)
        self.addCleanup(reader.close)
        result = reader.query(
            dict(
                task_id="heldout", text="error cargo-clippy is not installed", paths=[]
            )
        )
        self.assertEqual(result["results"][0]["document"], self.documents()[2])
        self.assertEqual(result["source_manifest_sha256"], receipt["source_sha256"])
        with self.assertRaises(ValueError):
            reader.query(dict(task_id="heldout", text="query", paths=[], gold="clippy"))

    def test_source_time_and_group_purging_reject_leakage(self):
        with self.assertRaises(ValueError):
            build(
                self.root / "future.sqlite3",
                self.documents(),
                train_until="2026-09-30T00:00:00Z",
            )
        with self.assertRaises(ValueError):
            build(
                self.root / "group.sqlite3",
                self.documents(),
                train_until="2026-10-20T00:00:00Z",
                excluded_groups=["group-1"],
            )
        self.assertFalse((self.root / "future.sqlite3").exists())

    def test_complete_inventory_counts_identical_copies_and_actual_hardlinks(self):
        root = self.root / "state"
        root.mkdir()
        (root / "one").write_bytes(b"abcd")
        (root / "two").write_bytes(b"abcd")
        os.link(root / "one", root / "hardlink")
        result = measure(
            [dict(name="state", path=str(root), kind="owner", private=True)]
        )
        self.assertEqual(
            (
                result["logical_bytes"],
                result["physical_payload_bytes"],
                result["file_entries"],
                result["physical_files"],
            ),
            (12, 8, 3, 2),
        )
        (root / "escape").symlink_to(self.root)
        with self.assertRaises(ValueError):
            measure([dict(name="state", path=str(root), kind="owner", private=True)])


if __name__ == "__main__":
    unittest.main()
