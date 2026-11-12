"""Synthetic contract checks only; no scientific or owner qualification."""
from dataclasses import replace
import math
import unittest

from real_time import (ClockSpec, ContractError, TimedAction, TimedFeedback,
                       frozen_real_time_credit, reward_discount, state_response, update_due)


class RealTimeTests(unittest.TestCase):
    def setUp(self):
        self.clock = ClockSpec("owner", "monotonic", "boot1", 100, 200, 300, 400)
        self.action = TimedAction("a", "a" * 64, "v1", self.clock.identity,
                                  0, ("perception", "control"), (0.5, -0.5))
        self.feedback = TimedFeedback("b" * 64, "a", "a" * 64, "v1",
                                      self.clock.identity, 0, 100, 200,
                                      self.action.group_ids, (1.0, -0.5))

    def credit(self, feedback=None, **kwargs):
        options = dict(clock=self.clock, model_version="v1", arm="routed",
                       cutoff_us=300, max_lag_us=1000)
        options.update(kwargs)
        return frozen_real_time_credit([self.action],
                                       [self.feedback] if feedback is None else feedback, **options)

    def test_endpoint_reward_and_waiting(self):
        for delay in (0, 100, 900):
            self.assertAlmostEqual(reward_discount(self.clock, value=2, decision_us=0,
                                                   reward_us=delay), 2 * math.exp(-delay / 100))
        self.assertNotEqual(self.credit().deltas, self.credit(
            [replace(self.feedback, available_us=300)]).deltas)

    def test_unit_scaling_preserves_math(self):
        scaled = ClockSpec("owner", "monotonic", "boot1", 100000, 200000, 300000, 400000)
        self.assertEqual(reward_discount(self.clock, value=1, decision_us=0, reward_us=100),
                         reward_discount(scaled, value=1, decision_us=0, reward_us=100000))
        self.assertEqual(state_response(self.clock, previous=0, observed=1, elapsed_us=100),
                         state_response(scaled, previous=0, observed=1, elapsed_us=100000))
        self.assertEqual(update_due(self.clock, last_update_us=0, now_us=300),
                         update_due(scaled, last_update_us=0, now_us=300000))
        self.assertEqual(self.credit().deltas, self.credit(
            [replace(self.feedback, outcome_us=100000, available_us=200000)],
            clock=scaled, cutoff_us=300000, max_lag_us=1000000).deltas)

    def test_clocks_are_independent(self):
        def outputs(clock):
            return (reward_discount(clock, value=1, decision_us=0, reward_us=100),
                    state_response(clock, previous=0, observed=1, elapsed_us=100),
                    update_due(clock, last_update_us=0, now_us=300), self.credit(clock=clock).deltas)
        for index, field in enumerate(("reward_discount_tau_us", "state_response_tau_us",
                                       "parameter_update_interval_us", "eligibility_tau_us")):
            changed = outputs(replace(self.clock, **{field: 900}))
            self.assertEqual(tuple(a == b for a, b in zip(outputs(self.clock), changed)),
                             tuple(i != index for i in range(4)))

    def test_future_payload_does_not_affect_frozen_prefix(self):
        future = replace(self.feedback, available_us=301, action_id=[],
                         model_version=None, source_digest=None,
                         modulator=(float("nan"),), outcome_us=-100)
        self.assertEqual(self.credit(), self.credit([self.feedback, future]))
        with self.assertRaises(ContractError):
            self.credit([replace(future, clock_identity=("owner", "monotonic", "boot2"))])
        with self.assertRaises(ContractError):
            self.credit([replace(future, available_us=True)])

    def test_bindings_and_chronology_rejected(self):
        for changes in ({"clock_identity": ("owner", "monotonic", "boot2")},
                        {"model_version": "v2"}, {"source_digest": "c" * 64},
                        {"action_us": 1}, {"group_ids": ("control", "perception")},
                        {"outcome_us": 201}, {"outcome_us": -1}):
            with self.subTest(changes=changes), self.assertRaises(ContractError):
                self.credit([replace(self.feedback, **changes)])
        with self.assertRaises(ContractError):
            self.credit([self.feedback, self.feedback])

    def test_routing_clipping_expiration_and_scalar(self):
        decay = math.exp(-0.5)
        for arm, expected in (("routed", (0.5 * decay, 0.25 * decay)),
                              ("shuffled", (-0.25 * decay, -0.5 * decay)),
                              ("scalar", (0.125 * decay, -0.125 * decay)),
                              ("no_eligibility", (0.0, 0.0))):
            self.assertEqual(self.credit(arm=arm).deltas, expected)
        self.assertEqual(self.credit(per_group_limit=0.1, global_l1_limit=0.1).deltas, (0.05, 0.05))
        expired = self.credit(max_lag_us=199)
        self.assertEqual((expired.deltas, expired.matched, expired.expired), ((0.0, 0.0), 0, 1))


if __name__ == "__main__":
    unittest.main()
