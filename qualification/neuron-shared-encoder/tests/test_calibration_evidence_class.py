"""Synthetic provenance-contract tests; callers cannot supply a higher class."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from neuron_shared_encoder.reader_runtime_receipt import (
    INCOMPLETE,
    REAL_MODEL_LOCAL_QUALIFICATION,
    REAL_SHADOW,
    ReaderRuntimeReceiptError,
    adapt_calibration_receipt,
)
from test_reader_runtime_declarations import calibration_payload

CONTEXT = {"candidate_id": "shared_head", "source_split": "ood"}
REAL_CLASSES = (REAL_MODEL_LOCAL_QUALIFICATION, REAL_SHADOW)


class CalibrationEvidenceClassTests(unittest.TestCase):
    def test_report_owned_class_is_preserved(self):
        for source_class in REAL_CLASSES:
            for caller_class in (None, source_class):
                with self.subTest(source=source_class, caller=caller_class):
                    receipt = adapt_calibration_receipt(
                        calibration_payload(source_class),
                        raw_evidence_class=caller_class,
                        **CONTEXT,
                    )
                    self.assertEqual(
                        (
                            receipt.status,
                            receipt.evidence_class,
                            receipt.raw_evidence_class,
                            receipt.authority,
                        ),
                        ("COMPLETE", source_class, source_class, "DENY_ALL"),
                    )

    def test_caller_cannot_change_report_class(self):
        for source_class in REAL_CLASSES:
            for caller_class in (*REAL_CLASSES, INCOMPLETE):
                if caller_class == source_class:
                    continue
                with self.subTest(source=source_class, caller=caller_class):
                    with self.assertRaises(ReaderRuntimeReceiptError):
                        adapt_calibration_receipt(
                            calibration_payload(source_class),
                            raw_evidence_class=caller_class,
                            **CONTEXT,
                        )

    def test_missing_or_null_report_class_cannot_be_filled_by_caller(self):
        for omitted in (False, True):
            payload = calibration_payload(REAL_SHADOW)
            if omitted:
                del payload["evidence_class"]
            else:
                payload["evidence_class"] = None
            for caller_class in (None, *REAL_CLASSES):
                with self.subTest(omitted=omitted, caller=caller_class):
                    with self.assertRaises(ReaderRuntimeReceiptError):
                        adapt_calibration_receipt(
                            payload, raw_evidence_class=caller_class, **CONTEXT
                        )
        with self.assertRaises(ReaderRuntimeReceiptError):
            adapt_calibration_receipt(None, raw_evidence_class=REAL_SHADOW, **CONTEXT)

    def test_malformed_report_or_caller_class_is_rejected(self):
        for value in ("", "unknown", False, 0, 1, 0.0, [], {}):
            for position in ("report", "caller"):
                with self.subTest(value=value, position=position):
                    payload = calibration_payload(REAL_MODEL_LOCAL_QUALIFICATION)
                    caller_class = REAL_SHADOW
                    if position == "report":
                        payload["evidence_class"] = value
                    else:
                        caller_class = value
                    with self.assertRaises(ReaderRuntimeReceiptError):
                        adapt_calibration_receipt(
                            payload, raw_evidence_class=caller_class, **CONTEXT
                        )

    def test_absent_calibration_remains_incomplete_without_claims(self):
        receipt = adapt_calibration_receipt(None, **CONTEXT)
        self.assertEqual(
            (
                receipt.status,
                receipt.evidence_class,
                receipt.raw_evidence_class,
                receipt.authority,
            ),
            ("INCOMPLETE", INCOMPLETE, INCOMPLETE, "DENY_ALL"),
        )


if __name__ == "__main__":
    unittest.main()
