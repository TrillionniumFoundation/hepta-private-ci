"""Exercise the genuine upstream functions and atomic source admission."""

import copy
from pathlib import Path
import shutil
import tempfile
import unittest

from . import data, repo_execution, upstream_panel_v4


class UpstreamPanelTests(unittest.TestCase):
    def test_real_references_and_tautologies_keep_business_distinction(self):
        old_confirmation = copy.deepcopy(repo_execution._CONFIRMATION)
        records = upstream_panel_v4.load_panel()
        self.assertEqual(
            {row["project_id"] for row in records},
            {"psf/requests", "pallets/werkzeug", "pallets/click"},
        )
        for record in records:
            with self.subTest(task=record["task_id"]):
                result = data.verify_answer(record, record["final_answer"])
                self.assertTrue(result["success"])
                self.assertTrue(result["result"]["executed"])
                self.assertEqual(result["result"]["controls_rejected"], 2)
                self.assertFalse(record["authorization"]["training_allowed"])
        self.assertEqual(repo_execution._CONFIRMATION, old_confirmation)

    def test_changed_source_refuses_without_partial_catalog_mutation(self):
        source = (
            Path(upstream_panel_v4.__file__).resolve().parents[2]
            / "qualification/cell-upstream-panel-20261118"
        )
        previous = copy.deepcopy(repo_execution._CATALOG)
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "panel"
            shutil.copytree(source, destination)
            path = destination / "sources/click_parser.py.txt"
            path.write_bytes(path.read_bytes() + b"\n# changed\n")
            with self.assertRaisesRegex(ValueError, "differs from GitHub blob"):
                upstream_panel_v4.load_panel(destination)
        self.assertEqual(repo_execution._CATALOG, previous)


if __name__ == "__main__":
    unittest.main()
