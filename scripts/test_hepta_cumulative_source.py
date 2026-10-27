#!/usr/bin/env python3
"""Small archive attack controls, with no model or remote artifacts."""

import hashlib
from pathlib import Path
import stat
import tempfile
import unittest
import zipfile

import hepta_cumulative_source as source


class RetainedSource(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.archive = self.root / "input.zip"
        self.output = self.root / "output"
        self.output.mkdir()

    def test_selected_bytes_are_verified_again_before_consumption(self):
        with zipfile.ZipFile(self.archive, "w") as archive:
            archive.writestr("chosen/checkpoint", b"selected")
            archive.writestr("not-selected", b"unused")
        members = source.extract(self.archive, self.output, {"chosen/checkpoint"})
        self.assertFalse((self.output / "not-selected").exists())
        path = source.pinned_member(
            self.output, dict(files=members), "chosen/checkpoint"
        )
        self.assertEqual(path.read_bytes(), b"selected")
        path.write_bytes(b"replaced")
        with self.assertRaisesRegex(ValueError, "evidence member changed"):
            source.pinned_member(self.output, dict(files=members), "chosen/checkpoint")

    def test_traversal_cannot_write_outside_the_owned_output(self):
        with zipfile.ZipFile(self.archive, "w") as archive:
            archive.writestr("../escaped", b"no")
        with self.assertRaisesRegex(ValueError, "unsafe archive member"):
            source.extract(self.archive, self.output, None)
        self.assertFalse((self.root / "escaped").exists())

    def test_link_members_are_not_materialized(self):
        entry = zipfile.ZipInfo("checkpoint")
        entry.create_system = 3
        entry.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(self.archive, "w") as archive:
            archive.writestr(entry, "../outside")
        with self.assertRaisesRegex(ValueError, "nonregular archive member"):
            source.extract(self.archive, self.output, None)
        self.assertFalse((self.output / "checkpoint").exists())

    def test_missing_selected_checkpoint_cannot_count_as_verified(self):
        with zipfile.ZipFile(self.archive, "w") as archive:
            archive.writestr("different", b"unused")
        with self.assertRaisesRegex(ValueError, "required checkpoint missing"):
            source.extract(self.archive, self.output, {"needed"})

    def test_replaced_index_digest_is_rejected(self):
        path = self.output / "receipt.json"
        path.write_bytes(b"new receipt")
        index = dict(
            files={
                "receipt.json": dict(
                    bytes=11, sha256=hashlib.sha256(b"old receipt").hexdigest()
                )
            }
        )
        with self.assertRaisesRegex(ValueError, "evidence member changed"):
            source.pinned_member(self.output, index, "receipt.json")


if __name__ == "__main__":
    unittest.main()
