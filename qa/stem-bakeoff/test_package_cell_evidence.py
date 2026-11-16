"""Data-archive determinism, deduplication, restoration and integrity checks."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from package_cell_evidence import collect_files, package, verify


class EvidencePackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.data = self.root / "data"
        self.data.mkdir()
        (self.data / "features.npz").write_bytes(bytes(range(256)) * 100)
        (self.data / "alias.npz").write_bytes((self.data / "features.npz").read_bytes())
        (self.data / "receipt.json").write_text('{"real_fixture":true}\n')
        self.provenance = {"git": {"repository": "https://example.invalid/repository",
            "commit": "a" * 40, "tree": "b" * 40, "code_sha256": {}}, "studies": {"fixture": True}}

    def build(self, name):
        archive = self.root / (name + ".tar.gz")
        index = package(collect_files(self.repo, {"run": self.data}), archive, self.provenance)
        return archive, self.root / (name + ".index.json"), index

    def test_same_bytes_produce_same_archive_despite_filename_and_mtime(self):
        first, first_index, details = self.build("one")
        os.utime(self.data / "features.npz", (123, 123))
        second, _, again = self.build("two")
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertEqual(details["archive"]["sha256"], again["archive"]["sha256"])
        self.assertEqual((details["file_count"], details["object_count"]), (3, 2))
        self.assertLess(details["unique_object_bytes"], details["logical_file_bytes"])
        self.assertEqual(verify(first, first_index)["verified_objects"], 2)

    def test_restore_recreates_independent_byte_exact_files(self):
        archive, index, _ = self.build("restore")
        output = self.root / "restored"
        result = verify(archive, index, output)
        self.assertTrue(result["restored"])
        for source in self.data.iterdir():
            self.assertEqual((output / "run" / source.name).read_bytes(), source.read_bytes())
        self.assertFalse(os.path.samefile(output / "run/features.npz", output / "run/alias.npz"))
        with self.assertRaisesRegex(ValueError, "new destination"):
            verify(archive, index, output)

    def test_corrupt_archive_and_forged_counter_reject(self):
        archive, index, _ = self.build("corruption")
        raw = archive.read_bytes()
        archive.write_bytes(raw + b"unbound trailing bytes")
        with self.assertRaisesRegex(ValueError, "external hash index"):
            verify(archive, index)
        archive.write_bytes(raw)
        altered = json.loads(index.read_bytes())
        altered["object_count"] = 999
        index.write_text(json.dumps(altered))
        with self.assertRaisesRegex(ValueError, "incomplete"):
            verify(archive, index)

    def test_repository_files_and_escaping_logical_paths_reject(self):
        (self.repo / "source.py").write_text("print('repository')\n")
        with self.assertRaisesRegex(ValueError, "Repository|repository"):
            collect_files(self.repo, {"code": self.repo})
        with self.assertRaisesRegex(ValueError, "escaping"):
            package({"../outside": self.data / "receipt.json"}, self.root / "bad.tar.gz", self.provenance)
        with self.assertRaisesRegex(ValueError, "escaping"):
            package({"C:/outside": self.data / "receipt.json"}, self.root / "bad.tar.gz", self.provenance)
        (self.data / "checkpoint.safetensors").write_bytes(b"weights")
        with self.assertRaisesRegex(ValueError, "checkpoint"):
            collect_files(self.repo, {"run": self.data})

    def test_archive_quota_failure_removes_only_new_output(self):
        with patch("package_cell_evidence.MAX_ARCHIVE_BYTES", 1), self.assertRaisesRegex(ValueError, "500 MB"):
            self.build("oversized")
        self.assertFalse((self.root / "oversized.tar.gz").exists())
        self.assertFalse((self.root / "oversized.index.json").exists())
        self.assertTrue((self.data / "features.npz").is_file())


if __name__ == "__main__":
    unittest.main()
