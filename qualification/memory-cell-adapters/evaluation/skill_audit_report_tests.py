"""Regression for report-size failure; invented data, no evidence or model run."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_audit_report import MAX_BYTES, SECTIONS, write_bounded_report


class SkillAuditReportTests(unittest.TestCase):
    def test_large_variable_records_round_trip_under_cap(self):
        report = {"passed": False, "quality_all_correct": False, "failed_checks": ["invented"],
                  "checks": {f"check-{i}": i != 1 for i in range(1200)},
                  "phase_records": [{"index": i, "trace": "x" * (2100 + i * 7)} for i in range(216)],
                  "cycle_source_state_identities": {str(i): {"source": "y" * 1700} for i in range(192)}}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "audit.json"
            write_bounded_report(output, report)
            restored = json.loads(output.read_bytes())
            parts = restored.pop("detail_parts")
            self.assertGreater(len(parts["phase_records"]), 1)
            for name in SECTIONS:
                restored[name] = {} if isinstance(report[name], dict) else []
                for number, record in enumerate(parts[name]):
                    raw = (output.parent / record["file"]).read_bytes()
                    self.assertLess(len(raw), MAX_BYTES)
                    self.assertEqual(len(raw), record["bytes"])
                    self.assertEqual(hashlib.sha256(raw).hexdigest(), record["sha256"])
                    body = json.loads(raw)
                    self.assertEqual((body["section"], body["part"]), (name, number))
                    self.assertEqual(len(body["records"]), record["records"])
                    if isinstance(restored[name], dict):
                        restored[name].update(body["records"])
                    else:
                        restored[name].extend(body["records"])
            self.assertEqual(restored, report)
            self.assertLess(output.stat().st_size, MAX_BYTES)

    def test_unrepresentable_record_refuses_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "audit.json"
            with self.assertRaisesRegex(ValueError, "Single audit detail record"):
                write_bounded_report(output, {"checks": {}, "phase_records": ["x" * MAX_BYTES],
                                             "cycle_source_state_identities": {}, "passed": True})
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
