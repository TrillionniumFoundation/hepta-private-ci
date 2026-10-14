"""Reject nonpinned historical data without touching publisher or BBC labels."""
from pathlib import Path
import tempfile
import unittest

from experiments.shared_stem_cell import external_bbc_shift as b
from experiments.shared_stem_cell import bbc_public_admission as a


class AdmissionTests(unittest.TestCase):
    def test_wrong_archived_zip_fails_before_any_publisher_access(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "not-our-original.zip"
            path.write_bytes(b"fake archive should not enter BBC source")
            with self.assertRaisesRegex(b.SourceError, "archive changed"):
                a.prior_texts(path)

    def test_missing_and_symlinked_original_archive_reject(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "missing.zip"
            with self.assertRaises(b.SourceError):
                a.prior_texts(path)
            target = Path(root) / "contents.zip"
            target.write_bytes(b"placeholder")
            path.symlink_to(target)
            with self.assertRaises(b.SourceError):
                a.prior_texts(path)

    def test_historical_archive_contract_is_exact_not_a_replacement_allowlist(self):
        self.assertEqual(len(a.ARCHIVE_SHA), 64)
        self.assertEqual(
            (a.PRODUCER, a.OLD_COHORT),
            ("hepta-public-study/dataset.jsonl",
             "hepta-fresh-confirmation/cohort.json"),
        )


if __name__ == "__main__":
    unittest.main()
