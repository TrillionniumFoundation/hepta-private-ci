"""Exercise frozen B2 material admission without making any model calls."""

import shutil
from pathlib import Path
import tempfile
import unittest

from . import blind_panel_v4, repo_execution

PANEL = (
    Path(__file__).resolve().parents[2] / "qualification/cell-blind-panel-b2-20261118"
)


class BlindPanelTests(unittest.TestCase):
    def test_originals_load_and_modified_license_is_rejected_atomically(self):
        records = blind_panel_v4.load_panel(PANEL)
        before = dict(repo_execution._CATALOG)
        with tempfile.TemporaryDirectory() as temporary:
            altered = Path(temporary) / "panel"
            shutil.copytree(PANEL, altered)
            license_path = next((altered / "sources").glob("*LICENSE.txt"))
            license_path.write_bytes(license_path.read_bytes() + b"changed")
            with self.assertRaisesRegex(ValueError, "differs from its commitment"):
                blind_panel_v4.load_panel(altered)
        self.assertEqual(repo_execution._CATALOG, before)
        self.assertEqual(
            [r["record_id"] for r in records],
            [r["record_id"] for r in blind_panel_v4.load_panel(PANEL)],
        )

    def test_modified_source_or_records_never_registers_new_fixtures(self):
        before = dict(repo_execution._CATALOG)
        with tempfile.TemporaryDirectory() as temporary:
            for relative in ("sources/django_http.py.txt", "prepared/records.jsonl"):
                altered = Path(temporary) / relative.replace("/", "_")
                shutil.copytree(PANEL, altered)
                path = altered / relative
                path.write_bytes(path.read_bytes() + b"changed")
                with self.assertRaisesRegex(ValueError, "differs from its commitment"):
                    blind_panel_v4.load_panel(altered)
                self.assertEqual(repo_execution._CATALOG, before)


if __name__ == "__main__":
    unittest.main()
