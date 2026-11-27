import hashlib
import json
import unittest

from qualification.hcsn_currentstate_n256_execution_admission_bridge.test_admission_bridge import (
    _records,
)
from qualification.hcsn_currentstate_n256_execution_receipt_contract import (
    receipt_contract,
)


def _seal(record):
    payload = dict(record)
    payload.pop("receipt_sha256", None)
    record["receipt_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return record


def _fixture():
    admission, freeze, manifest = _records()
    receipt = {
        "schema": receipt_contract.SCHEMA,
        "provider_admission_sha256": admission["admission_sha256"],
        "execution_freeze_sha256": freeze["freeze_sha256"],
        "result_manifest_sha256": hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "execution_key": admission["execution_key"],
        "capture_session_id": freeze["capture_session_id"],
        "host_alias": freeze["host_alias"],
        "execution_started_at_utc": "2026-11-15T01:12:00Z",
        "execution_completed_at_utc": "2026-11-15T01:58:00Z",
        "process_exit_code": 0,
        "execution_complete": True,
        "historical_negative_and_unknown_preserved": True,
        "largegrid_qualification": False,
        "production_adoption": False,
    }
    return _seal(receipt), admission, freeze, manifest


class ExecutionReceiptContractTests(unittest.TestCase):
    def test_exact_receipt_cross_binds_execution_and_manifest(self):
        receipt, admission, freeze, manifest = _fixture()
        result = receipt_contract.validate_future_execution_receipt(
            receipt, admission, freeze, manifest
        )
        self.assertEqual(
            result,
            receipt_contract.ExecutionReceiptResult(
                receipt_valid=True,
                manifest_bound=True,
                execution_key_bound=True,
                host_bound=True,
                interval_bound=True,
            ),
        )

    def test_out_of_window_completion_rejects(self):
        receipt, admission, freeze, manifest = _fixture()
        receipt["execution_completed_at_utc"] = "2026-11-15T02:11:00Z"
        _seal(receipt)
        with self.assertRaisesRegex(receipt_contract.ExecutionReceiptError, "interval"):
            receipt_contract.validate_future_execution_receipt(
                receipt, admission, freeze, manifest
            )

    def test_manifest_mutation_after_receipt_rejects(self):
        receipt, admission, freeze, manifest = _fixture()
        manifest["streams"]["candidate"]["payload_root_sha256"] = "f" * 64
        with self.assertRaisesRegex(receipt_contract.ExecutionReceiptError, "manifest"):
            receipt_contract.validate_future_execution_receipt(
                receipt, admission, freeze, manifest
            )

    def test_mixed_host_and_failed_exit_reject(self):
        receipt, admission, freeze, manifest = _fixture()
        receipt["host_alias"] = "other-host"
        _seal(receipt)
        with self.assertRaisesRegex(receipt_contract.ExecutionReceiptError, "host"):
            receipt_contract.validate_future_execution_receipt(
                receipt, admission, freeze, manifest
            )
        receipt, admission, freeze, manifest = _fixture()
        receipt["process_exit_code"] = 137
        _seal(receipt)
        with self.assertRaisesRegex(receipt_contract.ExecutionReceiptError, "successfully"):
            receipt_contract.validate_future_execution_receipt(
                receipt, admission, freeze, manifest
            )


if __name__ == "__main__":
    unittest.main()
