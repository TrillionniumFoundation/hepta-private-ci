"""Source-only controls for the N256 execution-receipt constructor."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from qualification.hcsn_currentstate_n256_execution_admission_bridge.test_admission_bridge import (
    _records,
)
from qualification.hcsn_currentstate_n256_execution_receipt_contract import (
    receipt_contract,
)
from qualification.hcsn_currentstate_n256_execution_receipt_publisher_intent import (
    publisher,
    static_inspector,
)


ROOT = Path(__file__).parent


def _write_records(folder):
    admission, freeze, manifest = _records()
    paths = {}
    for name, value in (
        ("admission", admission),
        ("freeze", freeze),
        ("manifest", manifest),
    ):
        path = folder / f"{name}.json"
        path.write_text(json.dumps(value))
        paths[name] = path
    return paths, admission, freeze, manifest


def _arguments(paths):
    return {
        "provider_admission_path": paths["admission"],
        "execution_freeze_path": paths["freeze"],
        "result_manifest_path": paths["manifest"],
        "execution_started_at_utc": "2026-11-15T01:12:00Z",
        "execution_completed_at_utc": "2026-11-15T01:58:00Z",
        "process_exit_code": 0,
        "execution_complete": True,
    }


class ExecutionReceiptPublisherIntentTests(unittest.TestCase):
    def test_missing_original_rejects_before_parent_validator(self):
        with mock.patch.object(
            receipt_contract, "validate_future_execution_receipt"
        ) as parent_gate:
            with self.assertRaises(publisher.ReceiptOriginalRequired):
                publisher.build_receipt_record(
                    provider_admission_path=None,
                    execution_freeze_path=None,
                    result_manifest_path=None,
                    execution_started_at_utc=None,
                    execution_completed_at_utc=None,
                    process_exit_code=None,
                    execution_complete=None,
                )
            parent_gate.assert_not_called()

    def test_synthetic_record_is_accepted_by_parent_validator(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths, admission, freeze, manifest = _write_records(Path(temporary))
            receipt = publisher.build_receipt_record(**_arguments(paths))
            result = receipt_contract.validate_future_execution_receipt(
                receipt, admission, freeze, manifest
            )
        self.assertTrue(result.receipt_valid)
        self.assertEqual(set(receipt), receipt_contract.FIELDS)
        self.assertTrue(receipt["historical_negative_and_unknown_preserved"])
        self.assertFalse(receipt["largegrid_qualification"])
        self.assertFalse(receipt["production_adoption"])

    def test_failed_exit_and_out_of_window_facts_reject(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths, _, _, _ = _write_records(Path(temporary))
            arguments = _arguments(paths)
            arguments["process_exit_code"] = 137
            with self.assertRaisesRegex(
                receipt_contract.ExecutionReceiptError, "successfully"
            ):
                publisher.build_receipt_record(**arguments)
            arguments = _arguments(paths)
            arguments["execution_completed_at_utc"] = "2026-11-15T02:11:00Z"
            with self.assertRaisesRegex(
                receipt_contract.ExecutionReceiptError, "interval"
            ):
                publisher.build_receipt_record(**arguments)

    def test_boolean_exit_code_cannot_alias_integer_zero(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths, _, _, _ = _write_records(Path(temporary))
            arguments = _arguments(paths)
            arguments["process_exit_code"] = False
            with self.assertRaisesRegex(ValueError, "not a boolean"):
                publisher.build_receipt_record(**arguments)

    def test_request_keeps_external_facts_unresolved(self):
        request = json.loads((ROOT / "REQUEST.json").read_text())
        self.assertTrue(
            all(value is None for value in request["required_external_originals"].values())
        )
        self.assertTrue(
            all(value is None for value in request["required_process_facts"].values())
        )
        self.assertIsNone(request["execution_key"])
        self.assertIsNone(request["execution_receipt_output_sha256"])
        self.assertFalse(request["numerical_execution_allowed"])
        self.assertTrue(request["historical_negative_and_unknown_preserved"])
        self.assertFalse(request["all_closed"])

    def test_static_inspector_reports_zero_execution(self):
        report = static_inspector.inspect(ROOT / "publisher.py", ROOT / "REQUEST.json")
        self.assertEqual(report["status"], "PASS_EXECUTION_RECEIPT_PUBLISHER_SOURCE_HOLD")
        self.assertEqual(report["external_originals_present"], 0)
        self.assertEqual(report["authentic_receipts_published"], 0)
        self.assertEqual(report["dynamic_runs"], 0)
        self.assertEqual(report["optimizer_steps"], 0)


if __name__ == "__main__":
    unittest.main()
