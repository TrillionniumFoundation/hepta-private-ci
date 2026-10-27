"""Transport integrity checks, independent of scientific outcome metrics."""

from pathlib import Path
import tempfile
import unittest

from maintenance.evidence import pack, unpack


class EvidenceArchiveTests(unittest.TestCase):
    def test_binary_and_text_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            (source / "results").mkdir(parents=True)
            (source / "results" / "values.bin").write_bytes(bytes(range(256)) * 3000)
            (source / "results" / "note.txt").write_text("Measured result, including failures.\n")
            manifest = pack(source, root / "archive", ["results"])
            result = unpack(root / "archive", root / "restore")
            self.assertEqual(result["files_verified"], 2)
            self.assertEqual(manifest["files"]["results/values.bin"]["bytes"], 768000)
            self.assertEqual((root / "restore/results/values.bin").read_bytes(), (source / "results/values.bin").read_bytes())

    def test_corrupt_part_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source").mkdir()
            (root / "source/data").write_text("actual evidence")
            pack(root / "source", root / "archive", ["data"])
            (root / "archive/evidence.tar.gz.part001").write_bytes(b"corrupt")
            with self.assertRaisesRegex(ValueError, "corrupt evidence part"):
                unpack(root / "archive", root / "restore")

    def test_linked_input_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source").mkdir()
            (root / "outside").write_text("not project evidence")
            (root / "source/link").symlink_to(root / "outside")
            with self.assertRaisesRegex(ValueError, "linked"):
                pack(root / "source", root / "archive", ["link"])


if __name__ == "__main__":
    unittest.main()
