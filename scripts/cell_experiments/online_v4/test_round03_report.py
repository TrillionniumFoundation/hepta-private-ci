"""An unavailable receipt cannot become a zero-cost completed experiment."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .round03_report import report_directory


class ReportReadTests(unittest.TestCase):
    def test_unreadable_receipt_remains_unknown_and_records_the_read_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt = root / "circuit/POOL.json"
            receipt.parent.mkdir()
            receipt.write_text("{}\n")
            with patch.object(
                Path, "read_text", side_effect=PermissionError("receipt unavailable")
            ):
                result = report_directory(root)
            self.assertEqual(result["status"], "INCOMPLETE")
            self.assertEqual(result["input_validation"], "INCOMPLETE")
            self.assertEqual(
                result["unreadable_artifacts"],
                [{"path": "circuit/POOL.json", "error": "receipt unavailable"}],
            )
            self.assertIsNone(result["shared_pool_initialization"])
            self.assertTrue(
                all(value is None for value in result["reported_scope_totals"].values())
            )
            self.assertFalse(result["scientific_qualification"])
