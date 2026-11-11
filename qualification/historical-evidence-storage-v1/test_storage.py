"""Storage boundary checks only; no worker, model or training execution."""

import gzip
from pathlib import Path
import sys
import tempfile
import unittest


sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cell-learning-loop-v1"))
from receipt_verifier import MAX_RECEIPT_BYTES, read_capture


class HistoricalStorageBoundary(unittest.TestCase):
    def test_plain_and_gzip_preserve_the_same_original_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.json"
            original = '{"text":"记忆 🧪","unknown_cost":null}\n'.encode()
            path.write_bytes(original)
            self.assertEqual(read_capture(path), original)
            path.unlink()
            path.with_suffix(".json.gz").write_bytes(gzip.compress(original, mtime=0))
            self.assertEqual(read_capture(path), original)

    def test_duplicate_storage_is_rejected_even_when_bytes_match(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.json"
            path.write_bytes(b"{}")
            path.with_suffix(".json.gz").write_bytes(gzip.compress(b"{}", mtime=0))
            with self.assertRaisesRegex(ValueError, "ambiguous"):
                read_capture(path)

    def test_corrupted_trailer_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.json"
            packed = bytearray(gzip.compress(b"{}", mtime=0))
            packed[-8] ^= 1
            path.with_suffix(".json.gz").write_bytes(packed)
            with self.assertRaisesRegex(ValueError, "invalid compressed"):
                read_capture(path)

    def test_expansion_cannot_exceed_the_original_capture_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.json"
            path.with_suffix(".json.gz").write_bytes(gzip.compress(b"x" * (MAX_RECEIPT_BYTES + 1), mtime=0))
            with self.assertRaisesRegex(ValueError, "exceeds"):
                read_capture(path)

    def test_missing_or_linked_storage_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.json"
            with self.assertRaisesRegex(ValueError, "missing"):
                read_capture(path)
            target = Path(directory) / "other.gz"
            target.write_bytes(gzip.compress(b"{}", mtime=0))
            path.with_suffix(".json.gz").symlink_to(target)
            with self.assertRaisesRegex(ValueError, "linked"):
                read_capture(path)


if __name__ == "__main__":
    unittest.main()
