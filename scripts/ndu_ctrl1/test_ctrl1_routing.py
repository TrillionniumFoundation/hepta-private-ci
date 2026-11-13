"""Counterexamples for learned computation routing and its frozen reference."""

from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
import json
import math
import unittest

from .evaluation import evaluate
from .learning import FEATURES, Learner, _sha
from .model import ACTIONS, Profile, Scenario, initial_state
from .routing import Router, RoutedController, train_router


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.profile = Profile()
        actor = [[0.0] * len(FEATURES) for _ in ACTIONS]
        actor[ACTIONS.index("stop")][0] = 2.0
        self.fast = Learner(
            "fitted_actor_critic", self.profile, actor, [0.0] * len(FEATURES), {}
        )
        self.scenarios = [
            Scenario(prior=Fraction(1), deadline=8, budget=10, horizon=3),
            Scenario(
                prior=Fraction(0), deadline=8, budget=10, horizon=3, stop_reward=0.9
            ),
            Scenario(deadline=0, budget=0, horizon=2),
        ]
        self.examples = [
            (
                s,
                replace(initial_state(s), budget_left=s.budget - 1)
                if s.budget
                else initial_state(s),
            )
            for s in self.scenarios
        ]
        self.router = train_router(
            self.examples, self.profile, self.fast, seed=17, epochs=32
        )

    def test_true_returns_keep_positive_negative_and_no_gain_cases(self):
        pairs = self.router.training["pairs"]
        self.assertEqual(len(pairs), 3)
        self.assertAlmostEqual(pairs[0]["fast_value"], 0.33)
        self.assertGreater(pairs[0]["delta"], 0)
        self.assertLess(pairs[1]["delta"], 0)
        self.assertEqual(pairs[2]["delta"], 0)
        self.assertEqual(pairs[2]["restored_base_credit"], 0)
        self.assertEqual(pairs[2]["one_slow_controller_credits"], 0)
        self.assertGreater(pairs[0]["one_slow_counters"]["forecast_calls"], 0)
        self.assertEqual(self.router.training["updates"], 96)
        self.assertGreater(self.router.predict(*self.examples[0]), 0)
        self.assertLess(self.router.predict(*self.examples[1]), 0)

    def test_checkpoint_replay_and_critical_identity_rejection(self):
        record = json.loads(json.dumps(self.router.record(), allow_nan=False))
        restored = Router.from_record(record)
        self.assertEqual(restored.record(), record)
        self.assertEqual(
            [restored.predict(*row) for row in self.examples],
            [self.router.predict(*row) for row in self.examples],
        )
        changes = []
        bad = deepcopy(record)
        bad["training"]["profile_sha256"] = "0" * 64
        changes.append(bad)
        bad = deepcopy(record)
        bad["training"]["pairs"][0]["delta"] += 0.5
        changes.append(bad)
        bad = deepcopy(record)
        bad["fast_parameters_sha256"] = "1" * 64
        changes.append(bad)
        for bad in changes:
            bad["checkpoint_sha256"] = _sha(
                {k: v for k, v in bad.items() if k != "checkpoint_sha256"}
            )
            with self.assertRaises(ValueError):
                Router.from_record(bad)
        unknown = {**record, "new_objective": True}
        with self.assertRaises(ValueError):
            Router.from_record(unknown)
        with self.assertRaises(ValueError):
            replace(self.router, weights=(math.nan,) * len(FEATURES))

    def test_positive_prediction_requests_paid_slow_and_nonpositive_uses_fast(self):
        scenario = self.scenarios[0]
        state = initial_state(scenario)
        positive = replace(self.router, weights=(1.0,) + (0.0,) * (len(FEATURES) - 1))
        negative = replace(self.router, weights=(-1.0,) + (0.0,) * (len(FEATURES) - 1))
        slow = RoutedController(scenario, self.profile, self.fast, positive)
        fast = RoutedController(scenario, self.profile, self.fast, negative)
        self.assertEqual(
            (slow.compute_charge(state).cost, slow.compute_charge(state).duration),
            (4, 1),
        )
        self.assertEqual(
            (fast.compute_charge(state).cost, fast.compute_charge(state).duration),
            (1, 0),
        )
        for exhausted in (replace(state, budget_left=0), replace(state, steps_left=0)):
            self.assertEqual(
                (
                    slow.compute_charge(exhausted).cost,
                    slow.compute_charge(exhausted).action,
                ),
                (0, "stop"),
            )
        sole_stop = replace(state, budget_left=1)
        before = slow.counters["router_predictions"]
        self.assertEqual(slow.compute_charge(sole_stop).cost, 1)
        self.assertEqual(slow.counters["router_predictions"], before)
        result = evaluate(scenario, self.profile, slow)
        self.assertTrue(math.isfinite(result["value"]))
        self.assertEqual(result["budget_violations"], 0)
        self.assertGreaterEqual(result["policy_gap"], -1e-10)

    def test_different_reference_or_unpaid_actionable_input_rejects(self):
        changed = Learner.from_record(self.fast.record())
        changed.actor[0][0] += 0.1
        with self.assertRaises(ValueError):
            RoutedController(self.scenarios[0], self.profile, changed, self.router)
        with self.assertRaises(ValueError):
            train_router(
                [(self.scenarios[0], initial_state(self.scenarios[0]))],
                self.profile,
                self.fast,
            )


if __name__ == "__main__":
    unittest.main()
