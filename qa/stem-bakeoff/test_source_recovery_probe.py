import gzip
from pathlib import Path
import tempfile
import unittest

from source_recovery_probe import canonical, digest, recover


class SourceRecoveryTests(unittest.TestCase):
    def test_exact_revision_restores_original_unicode_and_rejects_stale(self):
        with tempfile.TemporaryDirectory() as temporary:
            row = {"source_id": "issue:1", "source_version": "commit:abc", "problem_statement": "故障\nline2\r\n"}
            path = Path(temporary) / "bank.gz"
            path.write_bytes(gzip.compress(canonical(row) + b"\n", mtime=0))
            plan = [{"source_id": "issue:1", "source_version": version} for version in ("commit:abc", "commit:old")]
            result = recover(path, digest(path.read_bytes()), plan)
            self.assertEqual(result["results"][0]["recovered_sha256"], digest(canonical(row)))
            self.assertTrue(result["results"][0]["found"])
            self.assertFalse(result["results"][1]["found"])

    def test_tampering_or_ambiguous_revision_is_not_a_successful_read(self):
        with tempfile.TemporaryDirectory() as temporary:
            row = {"source_id": "issue:1", "source_version": "abc", "problem_statement": "text"}
            path = Path(temporary) / "bank.gz"
            path.write_bytes(gzip.compress(canonical(row) + b"\n"))
            original = digest(path.read_bytes())
            path.write_bytes(gzip.compress((canonical(row) + b"\n") * 2))
            with self.assertRaises(ValueError):
                recover(path, original, [{"source_id": "issue:1", "source_version": "abc"}])
            with self.assertRaises(ValueError):
                recover(path, digest(path.read_bytes()), [{"source_id": "issue:1", "source_version": "abc"}])


if __name__ == "__main__":
    unittest.main()
