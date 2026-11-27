"""Regress the historical fail-open decode and source-execution boundary."""

import base64
import gzip
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".github/scripts"))
from inspect_runtime_codex_archive import MAX_DECODED_BYTES, PAYLOADS, inspect_payload


class RuntimeCodexArchiveTests(unittest.TestCase):
    def inspect_source(self, directory, source):
        path = Path(directory) / "source.gz.b64"
        encoded = base64.b64encode(gzip.compress(source, mtime=0)) + b"\n"
        path.write_bytes(encoded)
        return inspect_payload(path, hashlib.sha256(encoded).hexdigest())

    def test_valid_source_is_parsed_without_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "must-not-exist"
            source = f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
            result = self.inspect_source(directory, source.encode())
            self.assertEqual(result["status"], "VALID_PYTHON_SOURCE_ONLY")
            self.assertFalse(marker.exists())
            self.assertFalse(result["source_executed"])
            self.assertFalse(result["source_applied"])

    def test_original_corrupt_payload_cannot_become_empty_source_success(self):
        path = ".github/runtime_codex_closure.py.gz.b64"
        result = inspect_payload(ROOT / path, PAYLOADS[path])
        self.assertEqual(result["status"], "INVALID_ARCHIVE")
        self.assertEqual(result["encoded_sha256"], PAYLOADS[path])
        self.assertIn("error_type", result)

    def test_hash_mismatch_is_rejected_before_decode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "changed.gz.b64"
            path.write_bytes(b"not base64 or gzip")
            result = inspect_payload(path, "0" * 64)
            self.assertEqual(result["status"], "INVALID_ARCHIVE")
            self.assertEqual(result["error"], "encoded historical payload hash differs")

    def test_decoded_size_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.inspect_source(directory, b"#" * (MAX_DECODED_BYTES + 1))
            self.assertEqual(result["status"], "INVALID_ARCHIVE")
            self.assertEqual(result["error"], "decoded source exceeds the byte bound")

    def test_invalid_python_is_not_reported_as_valid_source(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.inspect_source(directory, b"def broken(:\n")
            self.assertEqual(result["status"], "INVALID_ARCHIVE")
            self.assertEqual(result["error_type"], "SyntaxError")


if __name__ == "__main__":
    unittest.main()
