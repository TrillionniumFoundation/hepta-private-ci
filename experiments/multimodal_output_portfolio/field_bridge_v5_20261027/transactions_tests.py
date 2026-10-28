"""Independent synthetic transaction tests; no neural model or data is executed."""

from contextlib import ExitStack
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from ..field_bridge_v3_20261027.training_common import Costs
from . import transactions


class SyntheticJournal:
    def __init__(self):
        self.records = []

    def append(self, record):
        self.records.append(deepcopy(record))
        return str(len(self.records))


class SyntheticTransaction:
    """Instrument state and costs independently of the real learning primitives."""

    def __init__(self, guard_deltas, fail_step=None):
        self.model = SimpleNamespace(parameter=0.0, gradient=np.array([-1.0]), rng=0)
        self.optimizer = SimpleNamespace(momentum=0.0, lr=0.1)
        self.context = SimpleNamespace(
            protocol={}, seed=17, original=object(), costs=Costs(), action=2,
            guard=object(), observers={"reward": object()},
            baseline_guard={"values": {"reward": np.array([0.0])}},
            batches=lambda row: (row, row),
        )
        self.guard_deltas = iter(guard_deltas)
        self.fail_step = fail_step
        self.steps, self.restored = [], []
        self.journal = SyntheticJournal()

    def state_identity(self, model, optimizer):
        return {"parameters": model.parameter,
                "optimizer": {"momentum": optimizer.momentum, "lr": optimizer.lr}}

    def snapshot(self, model, optimizer):
        return {"parameter": model.parameter, "momentum": optimizer.momentum,
                "lr": optimizer.lr, "gradient": model.gradient.copy(), "rng": model.rng,
                "identity": self.state_identity(model, optimizer)}

    def restore(self, model, optimizer, saved):
        model.parameter, optimizer.momentum = saved["parameter"], saved["momentum"]
        optimizer.lr, model.gradient, model.rng = saved["lr"], saved["gradient"].copy(), saved["rng"]
        self.restored.append(deepcopy(saved))

    def schedule(self, seed, schedule_id, start, count, protocol):
        return [{"step": k, "noise_seed": seed * 1000 + schedule_id * 100 + k}
                for k in range(start, start + count)]

    def update(self, model, original, optimizer, adapt, clean, action, multiplier,
               noise_seed, protocol, costs):
        step = adapt["step"]
        costs.add("scheduled_gradient_microsteps")
        costs.add("gradient_backward_calls")
        self.steps.append((step, multiplier, noise_seed))
        model.gradient = np.array([float(step + 1)])
        model.rng += 1
        if multiplier:
            model.parameter += multiplier
            optimizer.momentum += 2 * multiplier
            optimizer.lr = 0.1 * multiplier
            costs.add("optimizer_steps")
        if step == self.fail_step:
            raise ArithmeticError("Synthetic failure after a partial state mutation")
        return {"loss": step / 100.0, "optimizer_advanced": multiplier != 0}

    def hard_panel(self, model, panel, observers, action, protocol, costs, name):
        costs.add("candidate_guard_calls")
        delta = next(self.guard_deltas)
        return {"values": {"reward": np.array([delta])},
                "output_sha256": ["synthetic-guard-output"]}

    def enter(self, stack):
        config = {"multipliers": [0.0, 0.25, 1.0, 2.0], "guard_min_delta": 0.0}
        stack.enter_context(patch.object(transactions, "configuration", return_value=config))
        stack.enter_context(patch.object(transactions, "frozen_base_hash", return_value="unchanged-base"))
        for name in ("snapshot", "restore", "schedule", "update", "hard_panel", "state_identity"):
            stack.enter_context(patch.object(transactions, name, side_effect=getattr(self, name)))
        return self

    def execute(self, start=0, action=2, grain=8):
        return transactions.execute(self.context, self.model, self.optimizer,
                                    start, action, 6000, grain, self.journal)


class GuardTransactionContracts(unittest.TestCase):
    def test_accept_prefix_reject_current_slice_and_consume_the_same_marks(self):
        with ExitStack() as stack:
            test = SyntheticTransaction([1, -1, 1, -1, 1, -1]).enter(stack)
            receipts = test.execute(start=96)
        self.assertEqual([r["start"] for r in receipts], list(range(96, 144, 8)))
        self.assertEqual([r["end"] for r in receipts], list(range(104, 145, 8)))
        self.assertEqual([r["after"]["parameters"] for r in receipts], [8, 8, 16, 16, 24, 24])
        self.assertEqual([r["accepted"] for r in receipts], [True, False, True, False, True, False])
        self.assertEqual(test.model.parameter, 24.0)
        self.assertEqual(test.optimizer.momentum, 48.0)
        np.testing.assert_array_equal(test.model.gradient, [136.0])
        self.assertEqual(test.model.rng, 24)
        self.assertEqual([step for step, _, _ in test.steps], list(range(96, 144)))
        self.assertTrue(all(multiplier == 1.0 for _, multiplier, _ in test.steps))
        self.assertEqual([mark for _, _, mark in test.steps],
                         [17 * 1000 + 6000 * 100 + step for step in range(96, 144)])
        self.assertEqual(test.context.costs.snapshot(), {
            "transaction_snapshots": 6, "scheduled_gradient_microsteps": 48,
            "gradient_backward_calls": 48, "optimizer_steps": 48,
            "candidate_guard_calls": 6, "accepted_blocks": 3,
            "rejected_blocks": 3, "discarded_gradient_microsteps": 24,
        })
        self.assertTrue(all(r["clock_advances_on_rejection"] for r in receipts))

    def test_all_rejections_preserve_entry_state_without_refunding_work(self):
        with ExitStack() as stack:
            test = SyntheticTransaction([-1] * 6).enter(stack)
            before = test.snapshot(test.model, test.optimizer)
            receipts = test.execute()
        after = test.snapshot(test.model, test.optimizer)
        for name in ("parameter", "momentum", "lr", "rng", "identity"):
            self.assertEqual(after[name], before[name])
        np.testing.assert_array_equal(after["gradient"], before["gradient"])
        self.assertEqual(test.context.costs.values["scheduled_gradient_microsteps"], 48)
        self.assertEqual(test.context.costs.values["discarded_gradient_microsteps"], 48)
        self.assertEqual(receipts[-1]["end"], 48)
        self.assertEqual(len(test.steps), 48)

    def test_zero_action_consumes_gradients_and_guards_but_not_optimizer_steps(self):
        with ExitStack() as stack:
            test = SyntheticTransaction([0] * 6).enter(stack)
            before = test.state_identity(test.model, test.optimizer)
            receipts = test.execute(action=0)
        self.assertEqual(test.state_identity(test.model, test.optimizer), before)
        self.assertEqual(test.context.costs.values["scheduled_gradient_microsteps"], 48)
        self.assertEqual(test.context.costs.values["candidate_guard_calls"], 6)
        self.assertEqual(test.context.costs.values.get("optimizer_steps", 0), 0)
        self.assertEqual(receipts[-1]["end"], 48)
        self.assertTrue(all(r["action_index"] == 0 for r in receipts))

    def test_exception_restores_active_slice_and_aborts_after_charged_partial_work(self):
        with ExitStack() as stack:
            test = SyntheticTransaction([1], fail_step=10).enter(stack)
            with self.assertRaisesRegex(ArithmeticError, "Synthetic failure"):
                test.execute()
        self.assertEqual(test.model.parameter, 8.0)
        self.assertEqual(test.optimizer.momentum, 16.0)
        self.assertEqual(test.optimizer.lr, 0.1)
        np.testing.assert_array_equal(test.model.gradient, [8.0])
        self.assertEqual(test.model.rng, 8)
        self.assertEqual([step for step, _, _ in test.steps], list(range(11)))
        self.assertEqual(test.context.costs.values["scheduled_gradient_microsteps"], 11)
        failures = [r for r in test.journal.records if r["kind"] == "transaction_exception"]
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["start"], 8)
        self.assertEqual(failures[0]["completed_microsteps"], 2)
        self.assertEqual(failures[0]["resources"]["scheduled_gradient_microsteps"], 3)
        self.assertEqual(failures[0]["after"], test.state_identity(test.model, test.optimizer))
        self.assertEqual(len([r for r in test.journal.records if r["kind"] == "transaction_start"]), 2)

    def test_guard48_delegates_to_the_original_transaction_with_identical_arguments(self):
        with ExitStack() as stack:
            test = SyntheticTransaction([]).enter(stack)
            receipt = {"start": 96, "end": 144, "accepted": True, "scope": "delegated"}
            delegate = stack.enter_context(patch.object(transactions, "guarded_block", return_value=receipt))
            self.assertEqual(test.execute(start=96, action=3, grain=48), [receipt])
            delegate.assert_called_once_with(test.context, test.model, test.optimizer, 96, 3, 6000)
        self.assertEqual(test.steps, [])
        records = [r for r in test.journal.records if r["kind"] == "transaction"]
        self.assertEqual(records, [{"kind": "transaction", "grain": 48, "receipt": receipt}])

    def test_guard48_exception_preserves_delegate_rollback_and_attempted_costs(self):
        with ExitStack() as stack:
            test = SyntheticTransaction([]).enter(stack)

            def failing_delegate(context, model, optimizer, start, action, schedule_id):
                saved = test.snapshot(model, optimizer)
                model.parameter, optimizer.momentum = 5.0, 10.0
                context.costs.add("scheduled_gradient_microsteps", 5)
                test.restore(model, optimizer, saved)
                raise ArithmeticError("Synthetic delegated failure")

            stack.enter_context(patch.object(transactions, "guarded_block", side_effect=failing_delegate))
            with self.assertRaisesRegex(ArithmeticError, "Synthetic delegated failure"):
                test.execute(start=48, grain=48)
        self.assertEqual(test.model.parameter, 0.0)
        self.assertEqual(test.optimizer.momentum, 0.0)
        self.assertEqual(len(test.restored), 1)
        self.assertEqual(len(test.journal.records), 1)
        record = test.journal.records[0]
        self.assertEqual((record["kind"], record["start"], record["grain"]),
                         ("transaction_exception", 48, 48))
        self.assertEqual(record["before"], record["after"])
        self.assertEqual(record["resources"], {"scheduled_gradient_microsteps": 5})


if __name__ == "__main__":
    unittest.main(verbosity=2)
