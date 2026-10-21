"""Status regression checks; fixture compliance is not model qualification."""

import copy
import hashlib
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "reader_diagnostic_status_candidate", ROOT / "scripts/hepta_sngr_reader_eval.py"
)
READER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(READER)


class DiagnosticStatusTests(unittest.TestCase):
    def test_real_ca276_completed_run_violates_registered_evidence_rule(self):
        raw = (
            Path(__file__).parent / "fixtures/ca276-hepta-reader-report.json"
        ).read_bytes()
        self.assertEqual(
            hashlib.sha256(raw).hexdigest(),
            "ddbea147e8b99727b9454aa9629eeec5d27ed92d405a8179317f06b9b1329ca8",
        )
        report = json.loads(raw)
        unchanged = copy.deepcopy(report)
        self.assertEqual(
            READER.diagnostic_execution_status(
                report["rows"], report["expected_model_calls"]
            ),
            {
                "execution_status": "completed",
                "diagnostic_contract_passed": False,
                "diagnostic_contract_failure_count": 38,
                "qualification_status": "not_qualified",
            },
        )
        self.assertEqual(report, unchanged)

    def test_compliant_fixture_still_does_not_claim_qualification(self):
        rows = [
            {"arm": arm, "prediction": prediction, "gold": "A"}
            for arm, prediction in (
                ("none", "UNKNOWN"),
                ("distractor", "UNKNOWN"),
                ("withheld", "UNKNOWN"),
                ("full", "A"),
            )
        ]
        unchanged = copy.deepcopy(rows)
        self.assertEqual(
            READER.diagnostic_execution_status(rows, 4),
            {
                "execution_status": "completed",
                "diagnostic_contract_passed": True,
                "diagnostic_contract_failure_count": 0,
                "qualification_status": "not_qualified",
            },
        )
        self.assertEqual(rows, unchanged)
        self.assertEqual(
            READER.diagnostic_execution_status(rows[:3], 4),
            {
                "execution_status": "incomplete",
                "diagnostic_contract_passed": False,
                "diagnostic_contract_failure_count": 0,
                "qualification_status": "not_qualified",
            },
        )


if __name__ == "__main__":
    unittest.main()
