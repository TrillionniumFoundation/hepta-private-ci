"""Subject selection and bounded receipt parsing regressions."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import platform_wire_receipt_subject as subject


class ReceiptSubjectTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / ".git").mkdir()

    def test_current_checkout_accepts_matching_receipts(self):
        with patch.object(subject.subprocess, "check_output", return_value="a" * 40):
            subject.require_selected_source(self.root, "a" * 40, None)

    def test_consistent_but_stale_receipts_reject(self):
        with patch.object(subject.subprocess, "check_output", return_value="b" * 40):
            with self.assertRaises(ValueError):
                subject.require_selected_source(self.root, "a" * 40, None)

    def test_explicit_subject_cannot_override_git_head(self):
        with patch.object(subject.subprocess, "check_output", return_value="b" * 40):
            with self.assertRaises(ValueError):
                subject.require_selected_source(self.root, "a" * 40, "a" * 40)

    def test_archive_requires_explicit_subject(self):
        (self.root / ".git").rmdir()
        with patch.object(subject.subprocess, "check_output", side_effect=OSError):
            with self.assertRaises(ValueError):
                subject.require_selected_source(self.root, "a" * 40, None)
            subject.require_selected_source(self.root, "a" * 40, "a" * 40)

    def test_archive_mismatched_subject_rejects(self):
        (self.root / ".git").rmdir()
        with patch.object(subject.subprocess, "check_output", side_effect=OSError):
            with self.assertRaises(ValueError):
                subject.require_selected_source(self.root, "a" * 40, "b" * 40)

    def test_invalid_explicit_identity_rejects(self):
        for expected in ("main", "A" * 40, "a" * 39, True):
            with self.subTest(expected=expected), self.assertRaises(ValueError):
                subject.require_selected_source(self.root, "a" * 40, expected)

    def test_broken_checkout_cannot_fall_back_to_archive(self):
        with patch.object(subject.subprocess, "check_output", side_effect=OSError):
            with self.assertRaises(ValueError):
                subject.require_selected_source(self.root, "a" * 40, "a" * 40)

    def test_invalid_git_identity_rejects(self):
        with patch.object(subject.subprocess, "check_output", return_value="invalid"):
            with self.assertRaises(ValueError):
                subject.require_selected_source(self.root, "a" * 40, "a" * 40)

    def test_reader_rejects_duplicate_and_nonobject_payloads(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipt.json"
            for raw in ('{"status":"failed","status":"passed"}', '[]', 'null'):
                path.write_text(raw)
                with self.subTest(raw=raw), self.assertRaises(ValueError):
                    subject.read_receipt(path)
            path.write_text('{"status":"failed"}')
            self.assertEqual(subject.read_receipt(path), {"status": "failed"})

    def test_reader_rejects_symlinks_and_oversize(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipt.json"
            path.write_text('{}')
            link = Path(directory) / "link.json"
            link.symlink_to(path)
            with self.assertRaises(ValueError):
                subject.read_receipt(link)
            path.write_bytes(b" " * (4 * 1024 * 1024 + 1))
            with self.assertRaises(ValueError):
                subject.read_receipt(path)


if __name__ == "__main__":
    unittest.main()
