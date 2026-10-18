"""A missing provenance assertion must never become a favorable default."""

import hashlib
import sys
import unittest
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from neuron_shared_encoder.reader_runtime_receipt import (  # noqa: E402
    INCOMPLETE,
    REAL_MODEL_LOCAL_QUALIFICATION,
    REAL_SHADOW,
    CalibrationReceiptV1,
    ReaderRuntimeReceiptError,
    ReaderRuntimeReceiptV1,
    adapt_calibration_receipt,
    adapt_runtime_receipt,
)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def runtime_payload(evidence_class: str) -> dict[str, object]:
    return {
        "receipt_id": "runtime.declarations",
        "checkpoint_receipt_digest": digest("checkpoint"),
        "runtime_digest": digest("runtime"),
        "device_id": "cpu0",
        "device_digest": digest("device"),
        "device_kind": "cpu",
        "precision": "fp32",
        "device_count": 1,
        "forward_calls": 64,
        "input_tokens": 100,
        "flops": 2.0,
        "peak_memory_bytes": 3.0,
        "p95_latency_ms": 4.0,
        "energy_mj": 5.0,
        "probability_digest": digest("probabilities"),
        "sample_count": 16,
        "evidence_class": evidence_class,
        "independent_new_source": True,
        "model_input_gold_visible": False,
    }


def calibration_payload(evidence_class: str) -> dict[str, object]:
    return {
        "calibration_id": "calibration.declarations",
        "heldout": True,
        "sample_count": 16,
        "probability_digest": digest("probabilities"),
        "metric_digest": digest("metrics"),
        "brier": 0.2,
        "ece": 0.1,
        "evidence_class": evidence_class,
        "independent_new_source": True,
    }


class ReaderRuntimeDeclarationTests(unittest.TestCase):
    def adapt_runtime(self, payload):
        return adapt_runtime_receipt(
            payload, candidate_id="shared_head", source_split="future"
        )

    def adapt_calibration(self, payload):
        return adapt_calibration_receipt(
            payload, candidate_id="shared_head", source_split="ood"
        )

    def assert_unknown(self, receipt, field, raw_class):
        self.assertFalse(receipt.complete)
        self.assertEqual(receipt.status, "INCOMPLETE")
        self.assertEqual(receipt.evidence_class, INCOMPLETE)
        self.assertEqual(receipt.raw_evidence_class, raw_class)
        self.assertEqual(receipt.missing_fields, (field,))
        self.assertIsNone(getattr(receipt, field))
        self.assertEqual(receipt.authority, "DENY_ALL")
        self.assertIs(receipt.next_snapshot_only, True)

    def test_missing_runtime_declarations_remain_incomplete(self):
        for raw_class in (REAL_SHADOW, REAL_MODEL_LOCAL_QUALIFICATION):
            for field in ("independent_new_source", "model_input_gold_visible"):
                with self.subTest(raw_class=raw_class, field=field):
                    payload = runtime_payload(raw_class)
                    del payload[field]
                    self.assert_unknown(self.adapt_runtime(payload), field, raw_class)

    def test_null_runtime_declarations_remain_incomplete(self):
        for raw_class in (REAL_SHADOW, REAL_MODEL_LOCAL_QUALIFICATION):
            for field in ("independent_new_source", "model_input_gold_visible"):
                with self.subTest(raw_class=raw_class, field=field):
                    payload = runtime_payload(raw_class)
                    payload[field] = None
                    self.assert_unknown(self.adapt_runtime(payload), field, raw_class)

    def test_runtime_contradictions_are_rejected(self):
        for field, value in (
            ("independent_new_source", False),
            ("model_input_gold_visible", True),
        ):
            with self.subTest(field=field):
                payload = runtime_payload(REAL_SHADOW)
                payload[field] = value
                with self.assertRaises(ReaderRuntimeReceiptError):
                    self.adapt_runtime(payload)

    def test_runtime_non_boolean_declarations_are_rejected(self):
        for field in ("independent_new_source", "model_input_gold_visible"):
            for value in ("true", "false", 0, 1, 0.0, 1.0, [], {}):
                with self.subTest(field=field, value=value):
                    payload = runtime_payload(REAL_SHADOW)
                    payload[field] = value
                    with self.assertRaises(ReaderRuntimeReceiptError):
                        self.adapt_runtime(payload)

    def test_explicit_runtime_declarations_preserve_raw_class(self):
        for raw_class in (REAL_SHADOW, REAL_MODEL_LOCAL_QUALIFICATION):
            with self.subTest(raw_class=raw_class):
                receipt = self.adapt_runtime(runtime_payload(raw_class))
                self.assertTrue(receipt.complete)
                self.assertEqual(receipt.evidence_class, raw_class)
                self.assertEqual(receipt.raw_evidence_class, raw_class)
                self.assertEqual(receipt.missing_fields, ())
                self.assertIs(receipt.independent_new_source, True)
                self.assertIs(receipt.model_input_gold_visible, False)
                self.assertEqual(receipt.authority, "DENY_ALL")

    def test_missing_or_null_calibration_independence_is_incomplete(self):
        field = "independent_new_source"
        for raw_class in (REAL_SHADOW, REAL_MODEL_LOCAL_QUALIFICATION):
            for omitted in (True, False):
                with self.subTest(raw_class=raw_class, omitted=omitted):
                    payload = calibration_payload(raw_class)
                    if omitted:
                        del payload[field]
                    else:
                        payload[field] = None
                    self.assert_unknown(
                        self.adapt_calibration(payload), field, raw_class
                    )

    def test_calibration_false_or_malformed_independence_is_rejected(self):
        for value in (False, "true", "false", 0, 1, 0.0, 1.0, [], {}):
            with self.subTest(value=value):
                payload = calibration_payload(REAL_SHADOW)
                payload["independent_new_source"] = value
                with self.assertRaises(ReaderRuntimeReceiptError):
                    self.adapt_calibration(payload)

    def test_explicit_calibration_independence_preserves_raw_class(self):
        for raw_class in (REAL_SHADOW, REAL_MODEL_LOCAL_QUALIFICATION):
            with self.subTest(raw_class=raw_class):
                receipt = self.adapt_calibration(calibration_payload(raw_class))
                self.assertTrue(receipt.complete)
                self.assertEqual(receipt.evidence_class, raw_class)
                self.assertEqual(receipt.raw_evidence_class, raw_class)
                self.assertEqual(receipt.missing_fields, ())
                self.assertIs(receipt.independent_new_source, True)
                self.assertEqual(receipt.authority, "DENY_ALL")

    def test_direct_complete_runtime_cannot_omit_declarations(self):
        complete = asdict(self.adapt_runtime(runtime_payload(REAL_SHADOW)))
        for field in ("independent_new_source", "model_input_gold_visible"):
            with self.subTest(field=field):
                values = dict(complete)
                del values[field]
                with self.assertRaises(ReaderRuntimeReceiptError):
                    ReaderRuntimeReceiptV1(**values)

    def test_direct_complete_calibration_cannot_omit_independence(self):
        values = asdict(self.adapt_calibration(calibration_payload(REAL_SHADOW)))
        del values["independent_new_source"]
        with self.assertRaises(ReaderRuntimeReceiptError):
            CalibrationReceiptV1(**values)


if __name__ == "__main__":
    unittest.main()
