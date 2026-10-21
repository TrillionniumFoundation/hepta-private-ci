"""Reader evidence cannot be relabelled with another caller's context."""

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from neuron_shared_encoder.reader_runtime_receipt import (  # noqa: E402
    INCOMPLETE,
    REAL_MODEL_LOCAL_QUALIFICATION,
    REAL_SHADOW,
    ReaderRuntimeReceiptError,
    adapt_calibration_receipt,
    adapt_runtime_receipt,
)
from test_reader_runtime_declarations import (  # noqa: E402
    calibration_payload,
    digest,
    runtime_payload,
)


class ReaderReceiptContextBindingTests(unittest.TestCase):
    def test_runtime_rejects_conflicting_or_malformed_context(self):
        for field, values in (
            ("candidate_id", ("other_model", None, "", False, 1, [], {})),
            ("source_split", ("ood", None, "", False, 1, [], {})),
        ):
            for value in values:
                with self.subTest(field=field, value=value):
                    payload = runtime_payload(REAL_SHADOW)
                    payload[field] = value
                    original = copy.deepcopy(payload)
                    with self.assertRaises(ReaderRuntimeReceiptError):
                        adapt_runtime_receipt(
                            payload, candidate_id="shared_head", source_split="future"
                        )
                    self.assertEqual(payload, original)

    def test_calibration_rejects_conflicting_or_malformed_context(self):
        for field, values in (
            ("candidate_id", ("other_model", None, "", False, 1, [], {})),
            ("source_split", ("future", None, "", False, 1, [], {})),
        ):
            for value in values:
                with self.subTest(field=field, value=value):
                    payload = calibration_payload(REAL_SHADOW)
                    payload[field] = value
                    original = copy.deepcopy(payload)
                    with self.assertRaises(ReaderRuntimeReceiptError):
                        adapt_calibration_receipt(
                            payload, candidate_id="shared_head", source_split="ood"
                        )
                    self.assertEqual(payload, original)

    def test_matching_runtime_context_preserves_complete_receipt(self):
        for evidence_class in (REAL_SHADOW, REAL_MODEL_LOCAL_QUALIFICATION):
            with self.subTest(evidence_class=evidence_class):
                payload = runtime_payload(evidence_class)
                expected = adapt_runtime_receipt(
                    payload, candidate_id="shared_head", source_split="future"
                )
                payload.update(candidate_id="shared_head", source_split="future")
                original = copy.deepcopy(payload)
                actual = adapt_runtime_receipt(
                    payload, candidate_id="shared_head", source_split="future"
                )
                self.assertEqual(actual.to_dict(), expected.to_dict())
                self.assertEqual(payload, original)

    def test_matching_calibration_context_preserves_complete_receipt(self):
        for evidence_class in (REAL_SHADOW, REAL_MODEL_LOCAL_QUALIFICATION):
            with self.subTest(evidence_class=evidence_class):
                payload = calibration_payload(evidence_class)
                expected = adapt_calibration_receipt(
                    payload, candidate_id="shared_head", source_split="ood"
                )
                payload.update(candidate_id="shared_head", source_split="ood")
                original = copy.deepcopy(payload)
                actual = adapt_calibration_receipt(
                    payload, candidate_id="shared_head", source_split="ood"
                )
                self.assertEqual(actual.to_dict(), expected.to_dict())
                self.assertEqual(payload, original)

    def test_incomplete_runtime_cannot_hide_conflicting_context(self):
        payload = runtime_payload(REAL_SHADOW)
        del payload["device_id"]
        payload["candidate_id"] = "other_model"
        with self.assertRaises(ReaderRuntimeReceiptError):
            adapt_runtime_receipt(
                payload, candidate_id="shared_head", source_split="future"
            )

    def test_incomplete_calibration_cannot_hide_conflicting_context(self):
        payload = calibration_payload(REAL_SHADOW)
        del payload["metric_digest"]
        payload["source_split"] = "future"
        with self.assertRaises(ReaderRuntimeReceiptError):
            adapt_calibration_receipt(
                payload, candidate_id="shared_head", source_split="ood"
            )

    def test_matching_checkpoint_does_not_change_receipt(self):
        payload = runtime_payload(REAL_SHADOW)
        original = copy.deepcopy(payload)
        expected = adapt_runtime_receipt(
            payload, candidate_id="shared_head", source_split="future"
        )
        actual = adapt_runtime_receipt(
            payload,
            candidate_id="shared_head",
            source_split="future",
            checkpoint_receipt_digest=payload["checkpoint_receipt_digest"],
        )
        self.assertEqual(actual.to_dict(), expected.to_dict())
        self.assertEqual(payload, original)

    def test_caller_cannot_replace_reported_checkpoint(self):
        payload = runtime_payload(REAL_SHADOW)
        original = copy.deepcopy(payload)
        with self.assertRaises(ReaderRuntimeReceiptError):
            adapt_runtime_receipt(
                payload,
                candidate_id="shared_head",
                source_split="future",
                checkpoint_receipt_digest=digest("other_checkpoint"),
            )
        self.assertEqual(payload, original)

    def test_invalid_caller_checkpoint_is_not_ignored(self):
        for value in ("", False, 0, [], {}, "not-a-digest"):
            with self.subTest(value=value):
                with self.assertRaises(ReaderRuntimeReceiptError):
                    adapt_runtime_receipt(
                        runtime_payload(REAL_SHADOW),
                        candidate_id="shared_head",
                        source_split="future",
                        checkpoint_receipt_digest=value,
                    )

    def test_caller_can_supply_a_previously_missing_checkpoint(self):
        expected_payload = runtime_payload(REAL_MODEL_LOCAL_QUALIFICATION)
        expected = adapt_runtime_receipt(
            expected_payload, candidate_id="shared_head", source_split="future"
        )
        for omitted in (True, False):
            with self.subTest(omitted=omitted):
                payload = dict(expected_payload)
                if omitted:
                    del payload["checkpoint_receipt_digest"]
                else:
                    payload["checkpoint_receipt_digest"] = None
                original = copy.deepcopy(payload)
                actual = adapt_runtime_receipt(
                    payload,
                    candidate_id="shared_head",
                    source_split="future",
                    checkpoint_receipt_digest=expected_payload[
                        "checkpoint_receipt_digest"
                    ],
                )
                self.assertEqual(actual.to_dict(), expected.to_dict())
                self.assertEqual(payload, original)

    def test_unknown_checkpoint_remains_incomplete(self):
        payload = runtime_payload(REAL_SHADOW)
        del payload["checkpoint_receipt_digest"]
        receipt = adapt_runtime_receipt(
            payload, candidate_id="shared_head", source_split="future"
        )
        self.assertEqual(receipt.status, "INCOMPLETE")
        self.assertEqual(receipt.evidence_class, INCOMPLETE)
        self.assertEqual(receipt.raw_evidence_class, REAL_SHADOW)
        self.assertEqual(receipt.missing_fields, ("checkpoint_receipt_digest",))
        self.assertIsNone(receipt.checkpoint_receipt_digest)
        self.assertEqual(receipt.authority, "DENY_ALL")
        self.assertIs(receipt.next_snapshot_only, True)

    def test_legacy_runtime_alias_preserves_complete_receipt_and_digest(self):
        for evidence_class in (REAL_SHADOW, REAL_MODEL_LOCAL_QUALIFICATION):
            with self.subTest(evidence_class=evidence_class):
                payload = runtime_payload(evidence_class)
                expected = adapt_runtime_receipt(
                    payload, candidate_id="shared_head", source_split="future"
                )
                payload["runtime_receipt_digest"] = payload.pop("runtime_digest")
                original = copy.deepcopy(payload)
                actual = adapt_runtime_receipt(
                    payload, candidate_id="shared_head", source_split="future"
                )
                self.assertEqual(actual.to_dict(), expected.to_dict())
                self.assertEqual(payload, original)

    def test_matching_runtime_aliases_preserve_complete_receipt_and_digest(self):
        for evidence_class in (REAL_SHADOW, REAL_MODEL_LOCAL_QUALIFICATION):
            with self.subTest(evidence_class=evidence_class):
                payload = runtime_payload(evidence_class)
                expected = adapt_runtime_receipt(
                    payload, candidate_id="shared_head", source_split="future"
                )
                payload["runtime_receipt_digest"] = payload["runtime_digest"]
                original = copy.deepcopy(payload)
                actual = adapt_runtime_receipt(
                    payload, candidate_id="shared_head", source_split="future"
                )
                self.assertEqual(actual.to_dict(), expected.to_dict())
                self.assertEqual(payload, original)

    def test_conflicting_runtime_aliases_are_rejected(self):
        for primary, alias in (
            (digest("runtime"), digest("other_runtime")),
            (None, digest("runtime")),
            (digest("runtime"), None),
        ):
            with self.subTest(primary=primary, alias=alias):
                payload = runtime_payload(REAL_SHADOW)
                payload["runtime_digest"] = primary
                payload["runtime_receipt_digest"] = alias
                original = copy.deepcopy(payload)
                with self.assertRaises(ReaderRuntimeReceiptError):
                    adapt_runtime_receipt(
                        payload, candidate_id="shared_head", source_split="future"
                    )
                self.assertEqual(payload, original)

    def test_invalid_runtime_alias_values_are_not_ignored(self):
        for field in ("runtime_digest", "runtime_receipt_digest"):
            for value in ("", False, 0, [], {}, "not-a-digest"):
                with self.subTest(field=field, value=value):
                    payload = runtime_payload(REAL_SHADOW)
                    payload["runtime_receipt_digest"] = payload["runtime_digest"]
                    payload[field] = value
                    with self.assertRaises(ReaderRuntimeReceiptError):
                        adapt_runtime_receipt(
                            payload, candidate_id="shared_head", source_split="future"
                        )

    def test_unknown_runtime_aliases_remain_incomplete(self):
        for bindings in (
            {},
            {"runtime_digest": None},
            {"runtime_receipt_digest": None},
            {"runtime_digest": None, "runtime_receipt_digest": None},
        ):
            with self.subTest(bindings=bindings):
                payload = runtime_payload(REAL_SHADOW)
                del payload["runtime_digest"]
                payload.update(bindings)
                receipt = adapt_runtime_receipt(
                    payload, candidate_id="shared_head", source_split="future"
                )
                self.assertEqual(receipt.status, "INCOMPLETE")
                self.assertEqual(receipt.evidence_class, INCOMPLETE)
                self.assertEqual(receipt.raw_evidence_class, REAL_SHADOW)
                self.assertEqual(receipt.missing_fields, ("runtime_digest",))
                self.assertIsNone(receipt.runtime_digest)
                self.assertEqual(receipt.authority, "DENY_ALL")
                self.assertIs(receipt.next_snapshot_only, True)


if __name__ == "__main__":
    unittest.main()
