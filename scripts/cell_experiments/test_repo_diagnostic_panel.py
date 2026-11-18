"""Exercise new curated packaging tasks through the existing business verifier."""

from pathlib import Path
import unittest

from . import data, repo_execution
from .protocol_v3 import require_prepared


class DiagnosticPanelTests(unittest.TestCase):
    def test_references_execute_and_tautologies_do_not_pass_controls(self):
        previous_confirmation = repo_execution._CONFIRMATION
        repo_execution.load_catalog("diagnostic")
        self.assertIs(repo_execution._CONFIRMATION, previous_confirmation)
        root = Path(__file__).resolve().parents[2]
        material = root / "qualification/cell-diagnostic-panel-20261118"
        arguments = ['"AMD64"', "0", '"dev"', '"codex.tar.gz"']
        records = [
            row
            for panel in ("c", "d")
            for row in data.load_records(material / panel / "prepared-records.jsonl")
        ]
        for record, literal in zip(records, arguments):
            with self.subTest(task=record["task_id"]):
                require_prepared(record)
                actual = data.verify_answer(record, record["final_answer"])
                self.assertTrue(actual["success"])
                self.assertTrue(actual["result"]["executed"])
                tautology = data.canonical(
                    {
                        "edits": [
                            {
                                "path": "test_contract.py",
                                "old": "    pass",
                                "new": f"    assert subject({literal}) == subject({literal})",
                            }
                        ]
                    }
                ).decode()
                invalid = data.verify_answer(record, tautology)
                self.assertTrue(invalid["result"]["result"]["original_passed"])
                self.assertEqual(invalid["result"]["controls_rejected"], 0)
                self.assertFalse(invalid["success"])


if __name__ == "__main__":
    unittest.main()
