"""Independent regressions for priced planning and actual joint evaluation."""

from dataclasses import replace
from fractions import Fraction
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ndu_ctrl1.evaluation import evaluate, sample_episode
from ndu_ctrl1.model import (
    Profile,
    Scenario,
    backup,
    initial_state,
    legal_actions,
    transitions,
)
from ndu_ctrl1.policies import Controller, Decision, Search, after_compute


class RepairLearner:
    def action(self, scenario, state):
        return "repair" if "repair" in legal_actions(scenario, state) else "stop"


class ObserveThenExecute:
    def choose(self, scenario, state):
        return Decision("execute" if state.used_mask else "observe", 1, 0)


class PlanningCostTests(unittest.TestCase):
    def test_prepaid_invocation_matches_predicted_and_actual_budget(self):
        scenario = Scenario(prior=Fraction(9, 10), horizon=1)
        state = initial_state(scenario)
        controller = Controller("mpc", Profile(), node_limit=96)
        charge = controller.compute_charge(state)
        decision = controller.choose(scenario, state)
        self.assertEqual((decision.cost, decision.duration), (4, 1))
        self.assertEqual(after_compute(state, decision), after_compute(state, charge))
        self.assertLess(decision.expanded_nodes, 32)
        self.assertGreater(decision.cost, 1 + math.ceil(decision.expanded_nodes / 32))
        self.assertIn(
            decision.action, legal_actions(scenario, after_compute(state, decision))
        )

    def test_future_value_pays_same_charge_and_leaf_is_not_free(self):
        scenario = Scenario(horizon=2)
        state = replace(
            initial_state(scenario),
            belief=Fraction(4, 5),
            budget_left=5,
            time_left=4,
            steps_left=1,
        )
        profile = Profile(
            risk=0, discount_per_second=1, latency_weight=0, resource_weight=0.1
        )
        controller = Controller("mpc", profile, node_limit=32)
        search = Search(scenario, profile, 512, owner=controller)
        # Execution: E[reward]=.8, E[environment cost]=1.7; future planning costs 2.
        self.assertAlmostEqual(search.value(state, 1), 0.8 - 0.1 * 1.7 - 0.1 * 2)
        self.assertAlmostEqual(search.value(state, 0), scenario.stop_reward - 0.1 * 2)
        decision = controller.choose(scenario, state)
        outcomes = transitions(
            scenario, after_compute(state, decision), decision.action
        )
        actual = -profile.resource_weight * decision.cost + backup(
            outcomes, [o.reward for o in outcomes], profile
        )
        self.assertAlmostEqual(search.value(state, 1), actual)

    def test_partial_comparison_returns_legal_action_and_pays_all_work(self):
        scenario = Scenario(horizon=3)
        controller = Controller("mpc", Profile(), node_limit=1)
        state = initial_state(scenario)
        decision = controller.choose(scenario, state)
        self.assertTrue(decision.fallback)
        self.assertEqual(
            (decision.expanded_nodes, decision.cost, decision.duration), (1, 2, 1)
        )
        self.assertEqual(decision.action, "stop")
        self.assertIn(
            decision.action, legal_actions(scenario, after_compute(state, decision))
        )
        episode = sample_episode(
            scenario, Profile(), Controller("mpc", Profile(), node_limit=1), 7
        )
        self.assertEqual(
            (
                episode["controller_cost"],
                episode["duration_seconds"],
                episode["budget_violations"],
            ),
            (2, 1, 0),
        )

    def test_voi_after_observation_delivers_and_cannot_repair_as_fallback(self):
        scenario = Scenario(deadline=12, budget=12, horizon=3)
        controller = Controller("voi", Profile(), learner=RepairLearner())
        for outcome in transitions(scenario, initial_state(scenario), "observe"):
            decision = controller.choose(scenario, outcome.next_state)
            self.assertIn(decision.action, ("stop", "execute"))
            self.assertEqual(
                (decision.cost, decision.duration, decision.route), (1, 0, "fast")
            )
            self.assertLessEqual(decision.forecast_calls, 2)
        partial = Controller("voi", Profile(), learner=RepairLearner(), node_limit=1)
        decision = partial.choose(scenario, initial_state(scenario))
        self.assertEqual(decision.action, "stop")
        self.assertTrue(decision.fallback)
        self.assertEqual(decision.cost, 2)

    def test_compute_fallback_and_emergency_never_exceed_budget(self):
        for scenario in (
            Scenario(budget=0),
            Scenario(budget=1),
            Scenario(deadline=0),
            Scenario(horizon=0),
        ):
            controller = Controller("mpc", Profile())
            state = initial_state(scenario)
            decision = controller.choose(scenario, state)
            admitted = after_compute(state, decision)
            self.assertIn(decision.action, legal_actions(scenario, admitted))
            episode = sample_episode(scenario, Profile(), controller, 0)
            self.assertLessEqual(
                episode["controller_cost"] + episode["environment_cost"],
                scenario.budget,
            )
            self.assertLessEqual(episode["duration_seconds"], scenario.deadline)
            self.assertEqual(episode["budget_violations"], 0)


class JointEvaluationTests(unittest.TestCase):
    def test_mean_prediction_is_evaluated_on_actual_joint_outcomes(self):
        profile = Profile(
            risk=0, discount_per_second=0.5, latency_weight=0, resource_weight=0
        )
        scenario = Scenario(horizon=1, stop_reward=0)
        state = initial_state(scenario)
        mean = Search(scenario, profile, 32, representation="mean").q(
            state, "execute", 1
        )
        self.assertEqual(mean, 0.125)
        result = evaluate(
            scenario, profile, Controller("mean_mpc", profile, node_limit=32)
        )
        # Actual joint execution value .203125, discounted by the paid planning second.
        self.assertEqual(result["value"], 0.5 * 0.203125)
        self.assertNotEqual(result["value"], 0.5 * mean)
        self.assertEqual(
            (result["actions"]["execute"], result["controller_cost"]), (1.0, 2.0)
        )

    def test_nested_policy_value_counts_each_successor_base_fee_once(self):
        scenario = Scenario(horizon=2)
        profile = Profile(risk=0.7, discount_per_second=0.8)
        start = initial_state(scenario)
        root = after_compute(start, Decision("observe", 1, 0))
        observations = transitions(scenario, root, "observe")
        continuations = []
        for outcome in observations:
            successor = after_compute(outcome.next_state, Decision("execute", 1, 0))
            terminal = transitions(scenario, successor, "execute")
            continuations.append(
                -profile.resource_weight
                + backup(terminal, [o.reward for o in terminal], profile)
            )
        expected = -profile.resource_weight + backup(
            observations, continuations, profile
        )
        result = evaluate(scenario, profile, ObserveThenExecute())
        self.assertAlmostEqual(result["value"], expected, places=12)
        self.assertEqual(
            (result["controller_cost"], result["decision_calls"]), (2.0, 2.0)
        )
        self.assertAlmostEqual(result["terminal_payoff"], 0.5, places=12)
        self.assertGreaterEqual(result["policy_gap"], 0)


if __name__ == "__main__":
    unittest.main()
