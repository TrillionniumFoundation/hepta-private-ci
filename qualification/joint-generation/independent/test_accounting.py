"""Accounting tests construct tiny tensors only; no experimental datasets."""

import unittest

import numpy as np

from independent.accounting import (
    AccountingError, BudgetExceeded, FairnessError, WorkLedger,
    compare_budgets, compare_ledgers, counted_model_class,
)
from model import JointModel


BASE_STAGES = ("base_decoder", "base_pretrain", "base_validation")
TRAIN_STAGES = (*BASE_STAGES, "search_train", "search_validation")


def shared_base():
    source = WorkLedger("shared-base")
    for stage in BASE_STAGES:
        source.charge_kernel(stage, "actual_base_kernel", scalar_ops=10, counts={"rows": 1})
    return source


def arm(name, source, *, useful_updates, update_units):
    ledger = WorkLedger(name, total_cap=10000)
    ledger.attribute_shared(source)
    ledger.record("search_train", units=update_units, optimizer_updates=useful_updates)
    ledger.charge_kernel("search_validation", "validation_kernel", scalar_ops=5)
    ledger.validation("search_validation", rows=3, selection=True)
    return ledger


class WorkLedgerTests(unittest.TestCase):
    def test_kernel_prices_and_snapshots_are_immutable(self):
        ledger = WorkLedger("arm", 1000)
        units = ledger.charge_kernel("search_train", "needed_kernel", macs=3, scalar_ops=2,
                                     exp_ops=1, counts={"optimizer_updates": 1})
        self.assertEqual(units, 16)
        self.assertEqual(ledger.consumed_units, 16)
        self.assertEqual(ledger.totals["op_macs"], 3)
        with self.assertRaises(TypeError):
            ledger.prices["macs"] = 1
        snapshot = ledger.snapshot()
        snapshot["stages"]["search_train"]["op_macs"] = 500
        self.assertEqual(ledger.totals["op_macs"], 3)
        with self.assertRaises(TypeError):
            ledger.charge_kernel("search_train", "typo", macss=3)

    def test_budget_refusal_and_invalid_counts_are_atomic(self):
        ledger = WorkLedger("arm", 20)
        ledger.charge_kernel("search_train", "one", scalar_ops=10)
        before = ledger.snapshot()
        with self.assertRaises(BudgetExceeded):
            ledger.charge_kernel("search_train", "too_large", exp_ops=2)
        self.assertEqual(ledger.snapshot(), before)
        for value in (-1, True, 1.5, 2**63):
            with self.assertRaises(AccountingError):
                ledger.record("search_train", units=value)
            self.assertEqual(ledger.snapshot(), before)

    def test_shared_base_is_charged_once_and_cannot_mutate_after_attribution(self):
        source = shared_base()
        left = arm("cheap", source, useful_updates=5, update_units=100)
        right = arm("ndu", source, useful_updates=2, update_units=400)
        self.assertEqual(left.snapshot()["stages"]["base_decoder"]["consumed_units"], 10)
        self.assertEqual(right.snapshot()["stages"]["base_decoder"]["consumed_units"], 10)
        before = left.snapshot()
        with self.assertRaises(AccountingError):
            left.attribute_shared(source)
        self.assertEqual(left.snapshot(), before)
        with self.assertRaises(AccountingError):
            source.record("base_pretrain", units=1, rows=1)

    def test_shared_cost_refusal_does_not_freeze_or_partially_copy_source(self):
        source = shared_base()
        recipient = WorkLedger("too_small", 29)
        before = recipient.snapshot()
        with self.assertRaises(BudgetExceeded):
            recipient.attribute_shared(source)
        self.assertEqual(recipient.snapshot(), before)
        source.record("base_pretrain", units=1, rows=1)
        self.assertEqual(source.consumed_units, 31)

    def test_same_budget_allows_more_cheap_useful_updates_without_padding(self):
        source = shared_base()
        cheap = arm("cheap", source, useful_updates=5, update_units=100)
        ndu = arm("ndu", source, useful_updates=2, update_units=400)
        ndu.critic_fit("critic_fit", rows=1, classes=1)
        policy = {"cheap": TRAIN_STAGES, "ndu": (*TRAIN_STAGES, "critic_fit")}
        result = compare_budgets([cheap, ndu], required_stages=policy)
        self.assertTrue(result["all_within_budget"])
        self.assertFalse(result["counter_equality_required"])
        self.assertGreater(cheap.totals["optimizer_updates"], ndu.totals["optimizer_updates"])
        self.assertNotIn("critic_fit", cheap.snapshot()["stages"])
        with self.assertRaises(FairnessError):
            compare_ledgers([cheap, ndu], required_stages=policy)

    def test_omitted_search_or_required_critic_cannot_pass(self):
        source = shared_base()
        left = arm("left", source, useful_updates=2, update_units=100)
        right = arm("right", source, useful_updates=2, update_units=100)
        compare_ledgers([left, right], required_stages=TRAIN_STAGES)
        with self.assertRaises(FairnessError):
            compare_budgets([left, right])  # Required critic was never fitted.
        right._stages.pop("search_validation")
        with self.assertRaises(FairnessError):
            compare_budgets([left, right], required_stages=TRAIN_STAGES)

    def test_different_caps_or_prices_cannot_pass(self):
        left, right = WorkLedger("left", 100), WorkLedger("right", 101)
        with self.assertRaises(FairnessError):
            compare_budgets([left, right], required_stages=())
        prices = dict(left.prices)
        prices["exp_ops"] = 1
        right = WorkLedger("right", 100, prices=prices)
        with self.assertRaises(FairnessError):
            compare_budgets([left, right], required_stages=())


class CountedModelTests(unittest.TestCase):
    def test_content_step_matches_original_and_records_actual_calls(self):
        ledger = WorkLedger("arm", 10**8)
        counted = counted_model_class(JointModel)(3, 2, 6, hidden=2, seed=11, ledger=ledger)
        original = JointModel(3, 2, 6, hidden=2, seed=11)
        x, labels = np.array([[0.2, 0.5, 0.8], [0.1, 0.3, 0.7]]), np.array([0, 1])
        with ledger.phase("search_train"):
            actual = counted.supervised_step(x, labels)
        expected = original.supervised_step(x, labels)
        self.assertEqual(actual, expected)
        for key in original.params:
            np.testing.assert_array_equal(counted.params[key], original.params[key])
        self.assertEqual(ledger.totals["model_forward_calls"], 2)
        self.assertEqual(ledger.totals["model_forward_macs"], 56)
        self.assertEqual(ledger.totals["model_backward_macs"], 44)
        self.assertEqual(ledger.totals["content_updates"], 1)
        self.assertNotIn("joint_utility_cells", ledger.totals)
        clone = counted.clone()
        self.assertIs(clone.ledger, ledger)
        other = WorkLedger("other", 10**8)
        self.assertIs(counted.clone(ledger=other).ledger, other)

    def test_decoder_updates_match_original_and_are_not_free(self):
        ledger = WorkLedger("arm", 10**8)
        counted = counted_model_class(JointModel)(3, 2, 6, hidden=2, seed=11, ledger=ledger)
        original = JointModel(3, 2, 6, hidden=2, seed=11)
        targets = np.zeros((2, 6))
        with ledger.phase("base_decoder"):
            actual = counted.fit_decoder(targets, steps=2)
        self.assertEqual(actual, original.fit_decoder(targets, steps=2))
        for key in original.params:
            np.testing.assert_array_equal(counted.params[key], original.params[key])
        self.assertEqual(ledger.totals["decoder_calls"], 3)
        self.assertEqual(ledger.totals["decoder_elements"], 36)
        self.assertEqual(ledger.totals["decoder_updates"], 2)
        self.assertGreater(ledger.consumed_units, 0)

    def test_no_unstaged_or_unfunded_inference(self):
        ledger = WorkLedger("arm", 0)
        model = counted_model_class(JointModel)(3, 2, 6, hidden=2, ledger=ledger)
        before = model.digest()
        with self.assertRaises(AccountingError):
            model.forward(np.zeros((1, 3)))
        with ledger.phase("search_train"):
            with self.assertRaises(BudgetExceeded):
                model.forward(np.zeros((1, 3)))
        self.assertEqual(model.digest(), before)
        self.assertEqual(ledger.consumed_units, 0)

    def test_utility_entry_point_cannot_silently_bypass_its_kernel_bill(self):
        ledger = WorkLedger("arm", 10**8)
        model = counted_model_class(JointModel)(3, 2, 6, hidden=2, ledger=ledger)
        x = np.zeros((1, 3))
        rewards = np.ones((1, 2, 2))
        with ledger.phase("search_train"):
            before = ledger.snapshot()
            with self.assertRaises(AccountingError):
                model.utility_step(x, rewards)
            self.assertEqual(ledger.snapshot(), before)
            model.utility_step(x, rewards, utility_units=100)
        self.assertEqual(ledger.totals["joint_utility_calls"], 1)
        self.assertEqual(ledger.totals["joint_utility_cells"], 4)


if __name__ == "__main__":
    unittest.main()
