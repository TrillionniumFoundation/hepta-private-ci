"""Transport identity tests; these do not exercise native signing or Agentd."""

from dataclasses import replace
import json
import unittest

from .contracts import (
    CalibrationReport,
    ModelIdentity,
    RiskPrediction,
    Scope,
    VerificationReceipt,
    digest,
)
from .kernel_payload import encode_kernel_payload, validate_payload_identity


def reports():
    scope = Scope("task", "attempt", "a" * 64, 1, "sqlite", "goal_error", 1, 4)
    model = ModelIdentity("b" * 64, None, "c" * 64)
    return (
        RiskPrediction(scope, model, 0.2, 1, "d" * 64),
        CalibrationReport(
            scope,
            model,
            (),
            ("cal",),
            ("confirm",),
            "e" * 64,
            "brier",
            "proper_scoring_rule",
            0.1,
            50,
            "unknown",
            ("frozen policy",),
        ),
        VerificationReceipt(
            scope,
            "readback_matches",
            (),
            "checker",
            "1",
            "d" * 64,
            1,
            "unknown",
            "等待读回",
            ("obtain readback",),
        ),
    )


class KernelPayloadTests(unittest.TestCase):
    def test_roundtrip_preserves_each_report_through_json_transport(self):
        for report in reports():
            payload = json.loads(
                json.dumps(encode_kernel_payload(report), ensure_ascii=False)
            )
            self.assertEqual(
                validate_payload_identity(
                    payload,
                    expected_record_sha256=digest(report),
                    expected_type=type(report),
                ),
                report,
            )

    def test_unknown_receipt_remains_unknown_despite_chain_support(self):
        receipt = reports()[2]
        payload = encode_kernel_payload(receipt)
        readback = validate_payload_identity(
            payload,
            expected_record_sha256=digest(receipt),
            expected_type=VerificationReceipt,
        )
        self.assertEqual(readback, receipt)
        with self.assertRaises(ValueError):
            validate_payload_identity(
                {"state": "supported", "evidence": []},
                expected_record_sha256=digest(receipt),
                expected_type=VerificationReceipt,
            )

    def test_rejects_tampering_unknown_fields_and_type_confusion(self):
        report = reports()[0]
        for change in (
            {"schema_version": True},
            {"schema_version": 2},
            {"signature_hex": "fake"},
            {"record_type": "verification_receipt"},
            {"record_encoding": "serde"},
            {"record_sha256": "e" * 64},
            {"record_json": "{}"},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_payload_identity(
                    {**encode_kernel_payload(report), **change},
                    expected_record_sha256=digest(report),
                    expected_type=RiskPrediction,
                )
        with self.assertRaises(ValueError):
            validate_payload_identity(
                encode_kernel_payload(report),
                expected_record_sha256=digest(report),
                expected_type=VerificationReceipt,
            )

    def test_recomputed_digest_cannot_replace_the_retained_identity(self):
        report = reports()[0]
        changed = replace(report, scope=replace(report.scope, state_version=2))
        with self.assertRaises(ValueError):
            validate_payload_identity(
                encode_kernel_payload(changed),
                expected_record_sha256=digest(report),
                expected_type=RiskPrediction,
            )

    def test_noncanonical_inner_json_and_oversized_payload_are_rejected(self):
        report = reports()[2]
        payload = encode_kernel_payload(report)
        payload["record_json"] = json.dumps(
            json.loads(payload["record_json"]), indent=2
        )
        with self.assertRaises(ValueError):
            validate_payload_identity(
                payload,
                expected_record_sha256=digest(report),
                expected_type=VerificationReceipt,
            )
        with self.assertRaises(ValueError):
            encode_kernel_payload(replace(report, reason="x" * 33000))


if __name__ == "__main__":
    unittest.main()
