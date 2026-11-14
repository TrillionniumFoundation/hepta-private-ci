"""Behavioral checks for finite CTRL-1 kernels and independent optimal values."""

from dataclasses import replace
from fractions import Fraction
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ndu_ctrl1.model import (
    Outcome,
    Profile,
    Scenario,
    backup,
    initial_state,
    legal_actions,
    transitions,
)
from ndu_ctrl1.oracle import Oracle, independent_tree_value


class ModelTests(unittest.TestCase):
    def test_posterior_conditions_on_signal_time_and_cost(self):
        scenario = Scenario()
        outcomes = transitions(scenario, initial_state(scenario), "observe")
        posterior = {
            (o.duration, o.cost, o.observation): o.next_state.belief for o in outcomes
        }
        self.assertEqual(posterior[(1, 1, "positive")], Fraction(27, 28))
        self.assertEqual(posterior[(3, 2, "positive")], Fraction(1, 4))
        self.assertEqual(
            sum(o.probability * o.next_state.belief for o in outcomes), scenario.prior
        )
        self.assertEqual(sum(o.probability for o in outcomes), 1)

    def test_worst_support_admission_not_expected_consumption(self):
        for scenario in (Scenario(budget=2), Scenario(deadline=2)):
            state = initial_state(scenario)
            self.assertNotIn("execute", legal_actions(scenario, state))
            with self.assertRaisesRegex(ValueError, "can exceed"):
                transitions(scenario, state, "execute")
        exhausted = Scenario(deadline=0, budget=0, horizon=0)
        self.assertEqual(legal_actions(exhausted, initial_state(exhausted)), ("stop",))

    def test_repair_changes_belief_without_revealing_outcome(self):
        scenario = Scenario(prior=Fraction(1, 4))
        outcomes = transitions(scenario, initial_state(scenario), "repair")
        successor = replace(
            initial_state(scenario),
            belief=Fraction(5, 8),
            time_left=6,
            budget_left=6,
            steps_left=3,
            used_mask=8,
        )
        self.assertEqual(
            outcomes, (Outcome(Fraction(1), 2, 2, "repair_attempted", successor, None),)
        )
        self.assertNotIn("repair", legal_actions(scenario, successor))

    def test_irrelevant_paid_observation_does_not_create_value(self):
        scenario = Scenario(
            prior=Fraction(4, 5),
            signal_accuracy=Fraction(1, 2),
            repair_success=Fraction(0),
        )
        profile = Profile(risk=0, discount_per_second=1)
        state = initial_state(scenario)
        oracle = Oracle(scenario, profile)
        self.assertEqual(oracle.action(state), "execute")
        for action in ("observe", "recall", "verify"):
            self.assertTrue(
                all(
                    o.next_state.belief == scenario.prior
                    for o in transitions(scenario, state, action)
                )
            )
            self.assertLess(oracle.q(state, action), oracle.value(state))

    def test_correlation_reversal_preserves_marginals_and_changes_value(self):
        positive = Scenario(outcome_correlation=1)
        negative = replace(positive, outcome_correlation=-1)
        lotteries = [
            transitions(s, initial_state(s), "execute") for s in (positive, negative)
        ]

        def marginal(outcomes, field):
            values = {getattr(o, field) for o in outcomes}
            return {
                value: sum(
                    o.probability for o in outcomes if getattr(o, field) == value
                )
                for value in values
            }

        for field in ("reward", "duration", "cost"):
            self.assertEqual(
                marginal(lotteries[0], field), marginal(lotteries[1], field)
            )
        profile = Profile(
            risk=0, discount_per_second=0.5, latency_weight=0, resource_weight=0
        )
        values = [
            backup(outcomes, [o.reward for o in outcomes], profile)
            for outcomes in lotteries
        ]
        self.assertEqual(values, [0.203125, 0.109375])
        fixed = [replace(s, variable_time=False) for s in (positive, negative)]
        self.assertEqual(
            [Oracle(s, profile).q(initial_state(s), "execute") for s in fixed],
            [0.125, 0.125],
        )
        for original, frozen in zip((positive, negative), fixed):
            self.assertEqual(
                marginal(
                    transitions(original, initial_state(original), "execute"), "cost"
                ),
                marginal(transitions(frozen, initial_state(frozen), "execute"), "cost"),
            )

    def test_complete_support_respects_limits_and_exact_probability(self):
        scenario = Scenario(horizon=2)
        pending, seen = [initial_state(scenario)], set()
        terminal_rewards = set()
        while pending:
            state = pending.pop()
            if state in seen:
                continue
            seen.add(state)
            for action in legal_actions(scenario, state):
                outcomes = transitions(scenario, state, action)
                self.assertEqual(sum(o.probability for o in outcomes), 1)
                for o in outcomes:
                    self.assertGreater(o.probability, 0)
                    self.assertLessEqual(o.cost, state.budget_left)
                    self.assertLessEqual(o.duration, state.time_left)
                    if o.next_state is not None:
                        pending.append(o.next_state)
                    else:
                        terminal_rewards.add(o.reward)
        self.assertEqual(terminal_rewards, {0.0, 0.35, 1.0})
        self.assertGreater(len(seen), 10)

    def test_profile_and_backup_reject_invalid_domains(self):
        for fields in (
            {"discount_per_second": 0},
            {"discount_per_second": 1.01},
            {"risk": -1},
            {"latency_weight": float("nan")},
            {"resource_weight": True},
            {"profile_id": "different"},
        ):
            with self.assertRaises(ValueError):
                Profile(**fields)
        profile = Profile(discount_per_second=1, risk=0)
        outcome = Outcome(Fraction(1), 2, 3, "success", None, 1.0)
        self.assertAlmostEqual(backup((outcome,), (1.0,), profile), 0.92)
        for value in (None, True, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                backup((outcome,), (value,), profile)
        with self.assertRaises(ValueError):
            backup((replace(outcome, probability=Fraction(1, 2)),), (1,), profile)
        with self.assertRaises(ValueError):
            backup((outcome,) * 513, (1,) * 513, profile)


class OracleTests(unittest.TestCase):
    def test_bellman_matches_independent_policy_tree_enumeration(self):
        scenario = Scenario(horizon=2, variable_time=False, budget=5, deadline=5)
        state = initial_state(scenario)
        for profile in (Profile(), Profile(risk=0, discount_per_second=1)):
            oracle = Oracle(scenario, profile)
            self.assertAlmostEqual(
                oracle.value(state),
                independent_tree_value(scenario, profile, state),
                places=12,
            )
            self.assertGreater(oracle.stats["expansion_count"], len(oracle.states))
            previous = oracle.stats
            oracle.action(state)
            self.assertEqual(oracle.stats, previous)

    def test_oracle_and_tree_have_explicit_caps(self):
        scenario = Scenario(horizon=2)
        state = initial_state(scenario)
        with self.assertRaisesRegex(ValueError, "Oracle state cap"):
            Oracle(scenario, Profile(), max_states=1).value(state)
        with self.assertRaisesRegex(ValueError, "enumeration cap"):
            independent_tree_value(scenario, Profile(), state, max_policy_trees=1)

    def test_small_risk_remains_finite_and_approaches_risk_neutral(self):
        scenario = Scenario(horizon=1)
        state = initial_state(scenario)
        small = Oracle(scenario, Profile(risk=1e-10)).q(state, "execute")
        neutral = Oracle(scenario, Profile(risk=0)).q(state, "execute")
        self.assertTrue(math.isfinite(small))
        self.assertAlmostEqual(small, neutral, places=9)


if __name__ == "__main__":
    unittest.main()
