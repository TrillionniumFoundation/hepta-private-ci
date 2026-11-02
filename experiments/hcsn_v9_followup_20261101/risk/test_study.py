"""Behavioral causal tests for the controlled service-risk intervention."""

from dataclasses import asdict
import unittest

from .study import (Forecast, ServiceModel, VIDEO_PLAN, initial_content,
                    make_worlds, planned, run_world)


class RiskTests(unittest.TestCase):
    def test_intervention_only_changes_explicit_risk(self):
        world = make_worlds()[0]
        content = initial_content(world)
        full = asdict(ServiceModel("full").estimate(content, VIDEO_PLAN, 1.03, 2.2))
        zero = asdict(ServiceModel("zero").estimate(content, VIDEO_PLAN, 1.03, 2.2))
        self.assertEqual(full.pop("deadline_miss_probability"), .5)
        self.assertEqual(zero.pop("deadline_miss_probability"), 0.)
        self.assertEqual(full, zero)
        full_plan, full_scores = planned(world, "full")
        zero_plan, zero_scores = planned(world, "zero")
        self.assertIsNone(full_plan)
        self.assertEqual(zero_plan, VIDEO_PLAN)
        full_content = [{k: v for k, v in x.items() if k not in
                        ("deadline_miss_probability", "score", "increment_over_stop")}
                        for x in full_scores["plans"]]
        zero_content = [{k: v for k, v in x.items() if k not in
                        ("deadline_miss_probability", "score", "increment_over_stop")}
                        for x in zero_scores["plans"]]
        self.assertEqual(full_content, zero_content)

    def test_fixed_actions_preserve_content(self):
        for world in make_worlds():
            full = run_world(world, "full", "logical")
            zero = run_world(world, "zero", "logical")
            full_on_zero = run_world(world, "full_on_zero", "logical")
            zero_on_full = run_world(world, "zero_on_full", "logical")
            for a, b in ((full, zero_on_full), (zero, full_on_zero)):
                self.assertEqual(a["receipt"]["output"], b["receipt"]["output"])
                self.assertEqual(a["net_utility"], b["net_utility"])

    def test_late_result_discarded_before_drain(self):
        run = run_world(make_worlds()[0], "zero", "logical")
        receipt = run["receipt"]
        self.assertEqual([e["status"] for e in receipt["events"]], ["accepted", "timed_out"])
        self.assertEqual(receipt["output"]["accepted_event_ids"], ("READ:audio:1",))
        self.assertEqual(run["drained_payloads"], 1)
        self.assertLess(receipt["output_elapsed_seconds"], receipt["post_drain_elapsed_seconds"])
        self.assertEqual(receipt["deadline_penalty"], 1.)
        self.assertEqual(receipt["requested_observations"], 2)
        self.assertEqual(receipt["observation_fee"], .04)

    def test_future_payload_and_delay_not_available_to_forecast(self):
        worlds = make_worlds()
        receipts = []
        for world in worlds:
            content = initial_content(world)
            receipts.append((world["audio"], Forecast().evaluate(content, None, VIDEO_PLAN),
                             planned(world, "full")[0], planned(world, "zero")[0]))
        for symbol in (0, 1):
            values = [x[1:] for x in receipts if x[0] == symbol]
            self.assertTrue(all(x == values[0] for x in values))


if __name__ == "__main__":
    unittest.main()
