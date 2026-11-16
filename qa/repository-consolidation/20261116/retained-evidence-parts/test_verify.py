#!/usr/bin/env python3
"""Exercise the retained evidence reader against real copied bytes."""

import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from verify import MANIFEST, REPOSITORY, verify


class EvidencePartsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.document = json.loads((REPOSITORY / MANIFEST).read_text())
        paths = [MANIFEST, self.document["codec_format_equivalence"]["path"]]
        for row in self.document["files"]:
            paths.append(row["path"] + ".parts.json")
            paths.extend(part["path"] for part in row["parts"])
        for row in self.document["controls"]:
            paths.extend((row["path"], row["original_copy"]))
        for path in paths:
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPOSITORY / path, target)
        self.first = self.root / self.document["files"][0]["parts"][0]["path"]

    def tearDown(self):
        self.temporary.cleanup()

    def test_complete_original_identities(self):
        original, report = verify(self.root)
        self.assertEqual(len(original), 9)
        self.assertEqual(report["parts"], 12)
        self.assertTrue(report["all_original_git_and_sha256_identities_match"])

    def test_changed_part_rejected(self):
        data = self.first.read_bytes()
        self.first.write_bytes(bytes([data[0] ^ 1]) + data[1:])
        with self.assertRaisesRegex(ValueError, "part identity"):
            verify(self.root)

    def test_truncated_part_rejected(self):
        self.first.write_bytes(self.first.read_bytes()[:-1])
        with self.assertRaisesRegex(ValueError, "part identity"):
            verify(self.root)

    def test_reordered_parts_rejected(self):
        document = copy.deepcopy(self.document)
        document["files"][0]["parts"].reverse()
        with self.assertRaisesRegex(ValueError, "part sequence"):
            verify(self.root, document)

    def test_path_escape_rejected(self):
        document = copy.deepcopy(self.document)
        document["files"][0]["parts"][0]["path"] = "../outside"
        with self.assertRaises(ValueError):
            verify(self.root, document)

    def test_symbolic_link_rejected(self):
        real = self.first.with_name(self.first.name + ".original")
        self.first.rename(real)
        self.first.symlink_to(real.name)
        with self.assertRaisesRegex(ValueError, "regular single-link"):
            verify(self.root)


if __name__ == "__main__":
    unittest.main()
