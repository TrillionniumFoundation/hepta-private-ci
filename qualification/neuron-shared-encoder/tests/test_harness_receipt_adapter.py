"""Contract tests use synthetic reports, not new model measurements."""

import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from neuron_shared_encoder.checkpoint_receipt import (
    INCOMPLETE,
    REAL_MODEL_LOCAL_QUALIFICATION,
    REAL_SHADOW,
    CheckpointReceiptError,
)
from neuron_shared_encoder.harness_receipt_adapter import (
    HarnessReceiptAdapterError,
    adapt_reader_report,
    require_real_shadow_from_report,
)


def d(value):
    return hashlib.sha256(value.encode()).hexdigest()


def complete(**extra):
    report = {
        "receipt_id": "harness.r1",
        "evidence_class": REAL_SHADOW,
        "checkpoint_loaded": True,
        "checkpoint_digest": d("checkpoint"),
        "model_digest": d("model"),
        "tokenizer_digest": d("tok"),
        "preprocessor_digest": d("prep"),
        "runtime_digest": d("runtime"),
        "reader_manifest_digest": d("manifest"),
        "source_digest": d("source"),
        "source_blob_digest": "a" * 40,
        "request_digest": d("request"),
        "held_label_digest": d("labels"),
        "checkpoint_digest_before": d("checkpoint"),
        "checkpoint_digest_after": d("checkpoint"),
        "production_selection_authority": False,
        "independent_new_source": True,
        "model_input_gold_visible": False,
        "current_run_mutation": False,
    }
    report.update(extra)
    return report


CONTEXT = {
    "candidate_id": "shared_head",
    "task_id": "reader.1",
    "source_split": "future",
}
DECLARATIONS = {
    "independent_new_source": True,
    "model_input_gold_visible": False,
    "current_run_mutation": False,
}


class HarnessReceiptAdapterTests(unittest.TestCase):
    def test_complete_report_is_preserved_and_denied(self):
        receipt = require_real_shadow_from_report(complete(), **CONTEXT)
        self.assertTrue(receipt.complete)
        self.assertEqual(receipt.evidence_class, REAL_SHADOW)
        self.assertEqual(receipt.authority, "DENY_ALL")
        for name, value in DECLARATIONS.items():
            self.assertIs(getattr(receipt, name), value)

    def test_local_report_never_promotes(self):
        receipt = adapt_reader_report(
            complete(evidence_class=REAL_MODEL_LOCAL_QUALIFICATION), **CONTEXT
        )
        self.assertEqual(receipt.evidence_class, REAL_MODEL_LOCAL_QUALIFICATION)
        with self.assertRaises(CheckpointReceiptError):
            receipt.require_real_shadow()

    def test_missing_identity_is_incomplete(self):
        receipt = adapt_reader_report(complete(tokenizer_digest=None), **CONTEXT)
        self.assertFalse(receipt.complete)
        self.assertEqual(receipt.evidence_class, INCOMPLETE)
        self.assertIn("tokenizer_digest", receipt.missing_fields)

    def test_mutation_and_checkpoint_drift_rejected(self):
        with self.assertRaises(HarnessReceiptAdapterError):
            adapt_reader_report(complete(checkpoint_digest_after=d("other")), **CONTEXT)
        with self.assertRaises(HarnessReceiptAdapterError):
            adapt_reader_report(complete(model_input_gold_visible=True), **CONTEXT)

    def test_missing_declarations_cannot_enter_real_gate(self):
        for name in DECLARATIONS:
            with self.subTest(field=name):
                report = complete()
                report.pop(name)
                with self.assertRaises(HarnessReceiptAdapterError):
                    require_real_shadow_from_report(report, **CONTEXT)

    def test_unknown_and_malformed_declarations_cannot_enter_real_gate(self):
        for name in DECLARATIONS:
            for value in (None, "true", "false", 0, 1, 0.0, 1.0, [], {}):
                with self.subTest(field=name, value=value):
                    with self.assertRaises(HarnessReceiptAdapterError):
                        require_real_shadow_from_report(
                            complete(**{name: value}), **CONTEXT
                        )

    def test_contradictory_report_cannot_be_overridden(self):
        for name, value in DECLARATIONS.items():
            with self.subTest(field=name):
                with self.assertRaises(HarnessReceiptAdapterError):
                    require_real_shadow_from_report(
                        complete(**{name: not value}),
                        independent_new_source=True,
                        **CONTEXT,
                    )

    def test_caller_declaration_only_corroborates_report(self):
        for value in (None, True):
            with self.subTest(corroborating=value):
                receipt = require_real_shadow_from_report(
                    complete(), independent_new_source=value, **CONTEXT
                )
                self.assertTrue(receipt.complete)
                self.assertEqual(receipt.authority, "DENY_ALL")
        for value in (False, "true", "false", 0, 1, 0.0, 1.0, [], {}):
            with self.subTest(invalid=value):
                with self.assertRaises(HarnessReceiptAdapterError):
                    require_real_shadow_from_report(
                        complete(), independent_new_source=value, **CONTEXT
                    )
        report = complete()
        report.pop("independent_new_source")
        with self.assertRaises(HarnessReceiptAdapterError):
            require_real_shadow_from_report(
                report, independent_new_source=True, **CONTEXT
            )

    def test_production_authority_marker_must_be_boolean_false(self):
        for value in (None, True, 0, 0.0, 1, 1.0, "false", "true", [], {}):
            with self.subTest(value=value):
                with self.assertRaises(HarnessReceiptAdapterError):
                    require_real_shadow_from_report(
                        complete(production_selection_authority=value), **CONTEXT
                    )

    def test_absent_optional_production_marker_keeps_adapter_denied(self):
        report = complete()
        report.pop("production_selection_authority")
        receipt = require_real_shadow_from_report(report, **CONTEXT)
        self.assertTrue(receipt.complete)
        self.assertEqual(receipt.authority, "DENY_ALL")


if __name__ == "__main__":
    unittest.main()
