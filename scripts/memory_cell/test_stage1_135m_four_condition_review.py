"""Read-only original-shard audit regressions, never new model generations."""

import os
from pathlib import Path
import shutil
import tempfile
import unittest

from stage1_135m_four_condition_review import audit, load, read_bytes, sha


class Archived135mReaderTests(unittest.TestCase):
    def test_duplicate_and_nonfinite_json_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "invalid.json"
            for raw in ('{"x":1,"x":2}', '{"x":NaN}'):
                path.write_text(raw)
                with self.assertRaises(ValueError):
                    load(path)

    def test_symlink_and_incomplete_original_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "real"
            path.write_bytes(b"source evidence")
            link = Path(d) / "alias"
            link.symlink_to(path)
            with self.assertRaisesRegex(ValueError, "linked"):
                read_bytes(link)
            self.assertEqual(sha(read_bytes(path)), sha(b"source evidence"))

    @unittest.skipUnless(
        os.environ.get("HEPTA_135M_SHARDS"), "original shards not mounted"
    )
    def test_complete_actual_135m_original_census(self):
        report = self.real()
        self.assertEqual(report["planned_attempts"], 32)
        self.assertEqual(report["successful_model_calls"], 26)
        self.assertEqual(report["missing_or_unavailable"], 6)
        self.assertEqual(report["arms"]["reviewed_minimal"]["unavailable"], 3)
        self.assertFalse(report["production_accepted"])

    @unittest.skipUnless(
        os.environ.get("HEPTA_135M_SHARDS"), "original shards not mounted"
    )
    def test_original_sha_manifest_detects_tampering(self):
        src = Path(os.environ["HEPTA_135M_SHARDS"])
        with tempfile.TemporaryDirectory() as d:
            dst = Path(d) / "experiment"
            shutil.copytree(src, dst)
            journal = dst / "shard-2/execution/raw-answers.jsonl"
            journal.write_bytes(journal.read_bytes() + b"forged")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                audit(dst, os.environ["HEPTA_135M_LABELS"])

    @unittest.skipUnless(
        os.environ.get("HEPTA_135M_SHARDS"), "original shards not mounted"
    )
    def test_wrong_generating_source_cannot_be_reclassified(self):
        with self.assertRaisesRegex(ValueError, "source"):
            self.real(source="0" * 40)

    def real(self, **kwargs):
        return audit(
            os.environ["HEPTA_135M_SHARDS"],
            os.environ["HEPTA_135M_LABELS"],
            **kwargs,
        )


if __name__ == "__main__":
    unittest.main()
