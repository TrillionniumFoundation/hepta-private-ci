import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from neuron_shared_encoder.reader_runtime_receipt import (  # noqa: E402
    INCOMPLETE,
    REAL_MODEL_LOCAL_QUALIFICATION,
    ReaderRuntimeReceiptError,
    adapt_calibration_receipt,
    adapt_runtime_receipt,
)


def d(s):
    return hashlib.sha256(s.encode()).hexdigest()


class T(unittest.TestCase):
    def test_real_runtime_missing_device_is_incomplete(self):
        r = adapt_runtime_receipt(
            {
                "receipt_id": "runtime.laya",
                "runtime_digest": d("r"),
                "calls": 64,
                "evidence_class": REAL_MODEL_LOCAL_QUALIFICATION,
            },
            candidate_id="shared_head",
            source_split="future",
            checkpoint_receipt_digest=d("c"),
        )
        self.assertFalse(r.complete)
        self.assertEqual(r.evidence_class, INCOMPLETE)
        self.assertEqual(r.raw_evidence_class, REAL_MODEL_LOCAL_QUALIFICATION)
        self.assertIn("device_id", r.missing_fields)
        self.assertEqual(r.authority, "DENY_ALL")

    def test_complete_runtime_requires_all_dimensions(self):
        p = {
            "receipt_id": "runtime.laya",
            "checkpoint_receipt_digest": d("c"),
            "runtime_digest": d("r"),
            "device_id": "cpu0",
            "device_digest": d("dev"),
            "device_kind": "cpu",
            "precision": "fp32",
            "device_count": 1,
            "calls": 64,
            "input_tokens": 100,
            "flops": 2.0,
            "peak_memory_bytes": 3.0,
            "p95_latency_ms": 4.0,
            "energy_mj": 5.0,
            "probability_digest": d("p"),
            "sample_count": 16,
            "evidence_class": REAL_MODEL_LOCAL_QUALIFICATION,
            "independent_new_source": True,
            "model_input_gold_visible": False,
        }
        r = adapt_runtime_receipt(p, candidate_id="shared_head", source_split="future")
        self.assertTrue(r.complete)
        self.assertEqual(r.evidence_class, REAL_MODEL_LOCAL_QUALIFICATION)
        self.assertEqual(len(r.receipt_digest), 64)

    def test_invalid_or_absent_calibration_is_incomplete(self):
        r = adapt_calibration_receipt(
            None, candidate_id="shared_head", source_split="future"
        )
        self.assertFalse(r.complete)
        self.assertEqual(r.evidence_class, INCOMPLETE)
        self.assertIn("sample_count", r.missing_fields)
        r = adapt_calibration_receipt(
            {
                "calibration_id": "cal.shared",
                "heldout": True,
                "sample_count": 0,
                "probability_digest": d("p"),
                "metric_digest": d("m"),
                "brier": float("nan"),
                "ece": 0.2,
                "evidence_class": REAL_MODEL_LOCAL_QUALIFICATION,
            },
            candidate_id="shared_head",
            source_split="future",
        )
        self.assertFalse(r.complete)
        self.assertEqual(r.evidence_class, INCOMPLETE)
        self.assertEqual(r.raw_evidence_class, REAL_MODEL_LOCAL_QUALIFICATION)

    def test_invalid_runtime_digest_is_rejected_without_zero_fill(self):
        with self.assertRaises(ReaderRuntimeReceiptError):
            adapt_runtime_receipt(
                {"receipt_id": "runtime.bad", "runtime_digest": "0" * 63 + "g"},
                candidate_id="shared_head",
                source_split="future",
            )

    def test_complete_calibration_is_held_out_and_denied(self):
        r = adapt_calibration_receipt(
            {
                "calibration_id": "cal.shared",
                "heldout": True,
                "sample_count": 16,
                "probability_digest": d("p"),
                "metric_digest": d("m"),
                "brier": 0.2,
                "ece": 0.1,
                "evidence_class": REAL_MODEL_LOCAL_QUALIFICATION,
                "independent_new_source": True,
            },
            candidate_id="shared_head",
            source_split="ood",
        )
        self.assertTrue(r.complete)
        self.assertEqual(r.authority, "DENY_ALL")


if __name__ == "__main__":
    unittest.main()
