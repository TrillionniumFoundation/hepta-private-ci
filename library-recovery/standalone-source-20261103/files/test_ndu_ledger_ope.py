import unittest
from dataclasses import FrozenInstanceError

from ndu_ledger_ope import (
    DecisionReceipt,
    MissingOutcomeError,
    OutcomeReceipt,
    ReceiptError,
    ReceiptLedger,
    SupportFailure,
    doubly_robust,
    effective_sample_size,
    ips,
    snips,
)


def decision(decision_id, behavior, selected, seed=1, budget=10.0):
    return DecisionReceipt.from_mapping(
        decision_id,
        tuple(behavior),
        behavior,
        seed,
        budget,
        selected,
    )


class LedgerGoldenTests(unittest.TestCase):
    def test_decision_receipt_is_complete_and_immutable(self):
        receipt = decision("d", {"a": 0.75, "b": 0.25}, "a", seed=42, budget=3)
        self.assertEqual(receipt.support, ("a", "b"))
        self.assertEqual(dict(receipt.propensity_map), {"a": 0.75, "b": 0.25})
        with self.assertRaises(FrozenInstanceError):
            receipt.selected_action = "b"
        with self.assertRaises(ReceiptError):
            decision("bad", {"a": 1.0}, "a", budget=-1)

    def test_ips_snips_dr_and_ess_golden_values(self):
        ledger = ReceiptLedger()
        ledger.add_decision(decision("d1", {"a": 0.5, "b": 0.5}, "a"))
        ledger.add_decision(decision("d2", {"a": 0.25, "b": 0.75}, "b"))
        ledger.add_outcome(OutcomeReceipt("o1", "d1", 2.0, 1))
        ledger.add_outcome(OutcomeReceipt("o2", "d2", 1.0, 1))
        target = {"a": 0.75, "b": 0.25}
        self.assertAlmostEqual(ips(ledger, target), 5.0 / 3.0)
        self.assertAlmostEqual(snips(ledger, target), 20.0 / 11.0)
        self.assertAlmostEqual(doubly_robust(ledger, target, {"a": 1.0, "b": 1.0}), 1.75)
        self.assertAlmostEqual(ledger.effective_sample_size(target), (11.0 / 6.0) ** 2 / (2.25 + 1.0 / 9.0))
        self.assertAlmostEqual(effective_sample_size([1.5, 1.0 / 3.0]), ledger.effective_sample_size(target))

    def test_missing_delayed_outcome_is_excluded_not_zero(self):
        ledger = ReceiptLedger()
        ledger.add_decision(decision("d1", {"a": 1.0}, "a"))
        ledger.add_decision(decision("d2", {"a": 1.0}, "a"))
        ledger.add_outcome(OutcomeReceipt("o1", "d1", 2.0, 1))
        ledger.add_outcome(OutcomeReceipt("pending", "d2", None, 5))
        estimate = ledger.evaluate("ips", {"a": 1.0}, as_of=1)
        self.assertTrue(estimate.valid)
        self.assertEqual(estimate.n, 1)
        self.assertEqual(estimate.missing_outcomes, 1)
        self.assertEqual(estimate.value, 2.0)
        ledger.add_outcome(OutcomeReceipt("o2", "d2", 4.0, 5))
        ledger.advance_watermark(5)
        self.assertAlmostEqual(ips(ledger, {"a": 1.0}), 3.0)

    def test_delayed_correction_replaces_original_after_watermark(self):
        ledger = ReceiptLedger()
        ledger.add_decision(decision("d", {"a": 1.0}, "a"))
        ledger.add_outcome(OutcomeReceipt("o1", "d", 2.0, 1))
        ledger.add_outcome(OutcomeReceipt("o2", "d", 5.0, 3, correction_of="o1"))
        self.assertEqual(ips(ledger, {"a": 1.0}, as_of=2), 2.0)
        self.assertEqual(ips(ledger, {"a": 1.0}, as_of=3), 5.0)

    def test_support_failure_is_invalid_and_strict(self):
        ledger = ReceiptLedger()
        ledger.add_decision(decision("d", {"a": 1.0, "b": 0.0}, "a"))
        ledger.add_outcome(OutcomeReceipt("o", "d", 2.0, 1))
        estimate = ledger.evaluate("ips", {"a": 0.0, "b": 1.0})
        self.assertFalse(estimate.valid)
        self.assertIn("support", (estimate.reason or "").lower())
        with self.assertRaises(SupportFailure):
            ips(ledger, {"a": 0.0, "b": 1.0})

    def test_no_outcome_is_invalid_not_zero(self):
        ledger = ReceiptLedger()
        ledger.add_decision(decision("d", {"a": 1.0}, "a"))
        estimate = ledger.evaluate("ips", {"a": 1.0})
        self.assertFalse(estimate.valid)
        self.assertIsNone(estimate.value)
        with self.assertRaises(MissingOutcomeError):
            ips(ledger, {"a": 1.0})


if __name__ == "__main__":
    unittest.main()
