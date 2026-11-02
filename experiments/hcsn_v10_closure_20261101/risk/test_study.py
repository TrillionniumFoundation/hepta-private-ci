"""Behavioral checks for bounded finalization and separate risk targets."""

from dataclasses import asdict
import unittest

from .execution import FinalizationBudget
from .study import (BUDGET, HARD_DEADLINE, ServiceModel, VIDEO,
                    run_world, select, worlds)


class ReservationTests(unittest.TestCase):
    def test_service_timeout_is_not_output_deadline_miss(self):
        model = ServiceModel("reserve")
        full = model.estimate(None, VIDEO, 1.1, 2.)
        zero = ServiceModel("reserve", True).estimate(None, VIDEO, 1.1, 2.)
        self.assertEqual(full, zero)
        self.assertEqual(full.deadline_miss_probability, 0.)
        self.assertEqual(model.records[0]["service_timeout_probability"], .5)

    def test_only_old_contract_has_distinct_risk_action(self):
        for world in worlds():
            self.assertIsNone(select(world, "old", False))
            self.assertEqual(select(world, "old", True), VIDEO)
            self.assertEqual(select(world, "reserve", False), VIDEO)
            self.assertEqual(select(world, "reserve", True), VIDEO)

    def test_reserve_flushes_before_hard_deadline_and_then_drains(self):
        result = run_world(worlds()[0], "reserve_full", "logical")
        receipt = result["receipt"]
        self.assertEqual([e["status"] for e in receipt["events"]], ["accepted", "timed_out"])
        self.assertEqual(receipt["output"]["accepted_event_ids"], ("READ:audio:1",))
        self.assertTrue(receipt["timely_output"])
        self.assertTrue(receipt["finalization"]["budget_satisfied"])
        self.assertEqual(receipt["deadline_penalty"], 0.)
        self.assertAlmostEqual(receipt["service_deadline_seconds"], HARD_DEADLINE-BUDGET.reserve_seconds)
        self.assertLess(receipt["output_elapsed_seconds"], HARD_DEADLINE)
        self.assertGreater(receipt["late_drains"][0]["start"], receipt["finalization"]["serialized_at"])
        self.assertLess(receipt["output_elapsed_seconds"], receipt["post_drain_elapsed_seconds"])

    def test_old_executor_type_adapter_and_deadline_artifact_retained(self):
        result = run_world(worlds()[0], "old_zero", "logical")
        self.assertFalse(result["receipt"]["timely_output"])
        self.assertEqual(result["receipt"]["deadline_penalty"], 1.)
        self.assertEqual(result["receipt"]["requested_observations"], 2)

    def test_fixed_requests_content_and_fee_rates_match(self):
        for world in worlds():
            for a, b in (("old_zero", "reserve_fixed_old_zero"),
                         ("reserve_full", "old_zero_fixed_reserve"),
                         ("reserve_full", "reserve_zero")):
                left, right = run_world(world, a, "logical"), run_world(world, b, "logical")
                self.assertEqual(left["receipt"]["output"]["probabilities"], right["receipt"]["output"]["probabilities"])
                self.assertEqual(left["receipt"]["requested_observations"], right["receipt"]["requested_observations"])
                self.assertEqual(left["receipt"]["observation_fee"], right["receipt"]["observation_fee"])

    def test_slow_head_and_sink_are_detected_not_hidden_by_reserve(self):
        for head, sink in ((.45, .015), (.015, .45)):
            result = run_world(worlds()[0], "reserve_fixed_old_zero", "logical",
                               head_delay=head, sink_delay=sink)
            self.assertFalse(result["receipt"]["finalization"]["budget_satisfied"])
            self.assertFalse(result["receipt"]["timely_output"])
            self.assertEqual(result["receipt"]["deadline_penalty"], 1.)
            self.assertEqual(result["drains"], 1)

    def test_invalid_budget_rejected_before_execution(self):
        for value in (-.01, float("inf"), True):
            with self.assertRaises(ValueError):
                FinalizationBudget(head_seconds=value)


if __name__ == "__main__":
    unittest.main()
