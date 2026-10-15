"""Tests for the research-only equal-budget differentiation gate."""

import unittest

from equal_budget_gate import ArmReceipt, BudgetGateRejected, compare_equal_budget


def arm(name, values=(6, 7, 8)):
    return ArmReceipt(
        name=name,
        trainable_parameters=9744,
        optimizer_bytes=38976,
        update_steps=48,
        encoder_forwards=224,
        exposed_train_rows=128,
        future_window_successes=values,
        complete_task_denominator=16,
    )


class EqualBudgetGateTests(unittest.TestCase):
    def test_equal_budget_is_reported_without_authority(self):
        result = compare_equal_budget(arm("typed"), arm("unsplit", (5, 7, 7)))
        self.assertTrue(result["equal_budget_verified"])
        self.assertEqual(result["future_window_deltas"], [1, 0, 1])
        self.assertTrue(result["three_future_windows_available"])
        self.assertFalse(result["statistical_or_causal_winner_selected"])
        self.assertFalse(result["ndu_authority_granted"])
        self.assertFalse(result["production_promotion_permitted"])
        self.assertEqual(result["authority"], "DENY_ALL")

    def test_budget_mismatch_fails_closed(self):
        changed = ArmReceipt(**{**arm("typed").__dict__, "optimizer_bytes": 1})
        with self.assertRaisesRegex(BudgetGateRejected, "optimizer_bytes"):
            compare_equal_budget(changed, arm("unsplit"))

    def test_missing_future_windows_fails_closed(self):
        with self.assertRaises(BudgetGateRejected):
            compare_equal_budget(arm("typed", ()), arm("unsplit", ()))

    def test_different_window_inventory_fails_closed(self):
        with self.assertRaises(BudgetGateRejected):
            compare_equal_budget(arm("typed", (1, 2)), arm("unsplit", (1,)))

    def test_authority_cannot_be_promoted_by_receipt(self):
        changed = ArmReceipt(**{**arm("typed").__dict__, "authority": "ALLOW"})
        with self.assertRaisesRegex(BudgetGateRejected, "DENY_ALL"):
            compare_equal_budget(changed, arm("unsplit"))


if __name__ == "__main__":
    unittest.main()
