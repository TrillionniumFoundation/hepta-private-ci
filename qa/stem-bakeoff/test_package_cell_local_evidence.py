import json
from pathlib import Path
import tempfile
import unittest

from package_cell_local_evidence import build, check


class LocalEvidenceTests(unittest.TestCase):
    def test_lossless_deduplicated_restore_and_tamper_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first, second = root / "first", root / "second"
            first.write_bytes(bytes(range(256)) * 10)
            second.write_bytes(b"distinct\0payload")
            archive = root / "evidence.tar.gz"
            report = build({"media/first": first, "repeat/first": first, "data/second": second}, archive,
                           {"git": "fixture", "study_seals": ["preserved"]})
            self.assertEqual(report["object_count"], 2)
            index = root / "evidence.tar.gz.index.json"
            result = check(archive, index, root / "restored")
            self.assertEqual(result["file_count"], 3)
            self.assertEqual((root / "restored/repeat/first").read_bytes(), first.read_bytes())
            self.assertNotEqual((root / "restored/repeat/first").stat().st_ino,
                                (root / "restored/media/first").stat().st_ino)
            with self.assertRaises(FileExistsError):
                check(archive, index, root / "restored")
            raw = archive.read_bytes()
            archive.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
            with self.assertRaisesRegex(ValueError, "hash index"):
                check(archive, index)

    def test_links_escaping_paths_and_overwrite_reject(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.write_bytes(b"data")
            link = root / "linked"
            link.symlink_to(source)
            with self.assertRaisesRegex(ValueError, "ordinary"):
                build({"valid": link}, root / "a.tar.gz", {})
            with self.assertRaisesRegex(ValueError, "escaping"):
                build({"../escape": source}, root / "b.tar.gz", {})
            archive = root / "c.tar.gz"
            build({"valid": source}, archive, {})
            with self.assertRaisesRegex(ValueError, "fresh"):
                build({"valid": source}, archive, {})

    def test_logical_file_ancestor_collision_rejects_before_creating_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "data"
            source.write_bytes(b"same bytes")
            for names in (("a", "a/b"), ("a", "a/b/c"), (".",)):
                target = root / "invalid.tar.gz"
                with self.assertRaisesRegex(ValueError, "ancestor"):
                    build({name: source for name in names}, target, {})
                self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
