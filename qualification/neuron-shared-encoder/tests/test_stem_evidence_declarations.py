"""Synthetic contract regressions; explicit flags are not independent evidence."""

import sys
import unittest
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from neuron_shared_encoder.stem_bridge import (
    ContractError,
    QualificationReceiptV1,
    ReaderGateReceiptV1,
)
from test_stem_bridge import receipt


def gate_values():
    return {
        "evidence_class": "REAL_SHADOW",
        "independent_new_source": True,
        "model_input_gold_visible": False,
        "reader_sufficient": True,
        "citation_coverage": 1.0,
        "future_lcb": 0.9,
        "baseline_ucb": 0.8,
        "old_task_degradation": 0.01,
        "ece": 0.02,
        "ood_false_acceptance": 0.001,
        "fallback_coverage": 1.0,
        "rollback_recovery": 1.0,
        "deleted_replay": 0,
    }


NON_BOOLEANS = (None, "false", "true", 0, 1, 0.0, 1.0, [], {})


class StemEvidenceDeclarationTests(unittest.TestCase):
    def test_missing_declarations_cannot_construct_receipts(self):
        for constructor, values in (
            (QualificationReceiptV1, asdict(receipt())),
            (ReaderGateReceiptV1, gate_values()),
        ):
            for name in ("independent_new_source", "model_input_gold_visible"):
                with self.subTest(receipt=constructor.__name__, field=name):
                    missing = dict(values)
                    del missing[name]
                    with self.assertRaises(TypeError):
                        constructor(**missing)

    def test_unknown_malformed_or_contradictory_declarations_are_rejected(self):
        for constructor, values in (
            (QualificationReceiptV1, asdict(receipt())),
            (ReaderGateReceiptV1, gate_values()),
        ):
            for name, required in (
                ("independent_new_source", True),
                ("model_input_gold_visible", False),
            ):
                for value in (not required, *NON_BOOLEANS):
                    with self.subTest(
                        receipt=constructor.__name__, field=name, value=value
                    ):
                        with self.assertRaises(ContractError):
                            constructor(**{**values, name: value})

    def test_reader_sufficiency_must_be_boolean(self):
        for value in NON_BOOLEANS:
            with self.subTest(value=value):
                with self.assertRaises(ContractError):
                    ReaderGateReceiptV1(**{**gate_values(), "reader_sufficient": value})

    def test_insufficient_reader_cannot_pass_real_shadow_gate(self):
        values = {**gate_values(), "reader_sufficient": False}
        gate = ReaderGateReceiptV1(**values).to_split_gate()
        self.assertFalse(gate.passes)
        self.assertIn("reader_evidence_insufficient", gate.reasons())


if __name__ == "__main__":
    unittest.main()
