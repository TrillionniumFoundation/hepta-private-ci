"""Behavioral regressions against complete frozen-environment evaluation.

The checkpoints here are bounded synthetic fixtures, not trained candidates.
Neither these tests nor their concrete counterexample qualify an adoption.
"""

from collections import deque
from dataclasses import replace
from fractions import Fraction
import unittest

from ndu_ctrl1.evaluation import evaluate, sample_episode
from ndu_ctrl1.learning import FEATURES, Learner
from ndu_ctrl1.model import ACTIONS, Profile, Scenario, initial_state, transitions
from ndu_ctrl1.policies import Controller, Decision, Search, after_compute
from ndu_ctrl1.routing import _OneSlow
from ndu_real_runtime.objective import certainty_equivalent, edge_value

from .continuation import OneSlowControllerV2


def fixture_fast(profile, priorities=("execute",)):
    actor = [[0.0] * len(FEATURES) for _ in ACTIONS]
    for weight, action in enumerate(reversed(priorities), 1):
        actor[ACTIONS.index(action)][0] = float(weight)
    return Learner("fitted_actor_critic", profile, actor, [0.0] * len(FEATURES), {})


class ForcedRootThenFast:
    """Independent execution adapter: force one root, then invoke fast directly."""

    def __init__(self, root, profile, fast, decision):
        self.root, self.decision = root, decision
        self.fast = Controller("fast", profile, Learner.from_record(fast.record()))

    def choose(self, scenario, state):
        return (
            self.decision if state == self.root else self.fast.choose(scenario, state)
        )


def path_lottery(scenario, profile, policy, state):
    """Flatten complete environment paths, deliberately unlike nested utility."""
    decision = policy.choose(scenario, state)
    admitted = after_compute(state, decision)
    lottery = []
    for outcome in transitions(scenario, admitted, decision.action):
        children = (
            [(Fraction(1), outcome.reward)]
            if outcome.next_state is None
            else path_lottery(scenario, profile, policy, outcome.next_state)
        )
        for mass, value in children:
            path_value = -profile.resource_weight * decision.cost + edge_value(
                decision.duration,
                -profile.resource_weight * outcome.cost
                + edge_value(outcome.duration, value, profile),
                profile,
            )
            lottery.append((outcome.probability * mass, path_value))
    return lottery


class ContinuationTests(unittest.TestCase):
    def test_root_action_changes_without_budget_exhaustion_or_a_new_objective(self):
        profile = Profile()
        scenario = Scenario(
            prior=Fraction(1, 3),
            budget=10,
            horizon=2,
            variable_time=False,
            repair_success=Fraction(2, 3),
        )
        root, fast = initial_state(scenario), fixture_fast(profile)
        old = _OneSlow(root, profile, fast)
        new = OneSlowControllerV2(scenario, root, profile, fast)
        old_decision = old.choose(scenario, root)
        new_decision = new.choose(scenario, root)
        self.assertEqual((old_decision.action, new_decision.action), ("stop", "repair"))
        self.assertEqual(
            (old_decision.cost, old_decision.duration, old_decision.fallback),
            (new_decision.cost, new_decision.duration, new_decision.fallback),
        )
        self.assertFalse(old_decision.fallback)
        self.assertTrue(new.forecast.complete)
        old_result = evaluate(scenario, profile, old)
        new_result = evaluate(scenario, profile, new)
        self.assertGreater(new_result["value"], old_result["value"])
        self.assertAlmostEqual(
            dict(new.forecast.root_action_values)["repair"],
            new_result["value"],
            places=12,
        )
        self.assertEqual(
            (
                new_result["actions"],
                new_result["controller_cost"],
                new_result["controller_seconds"],
                new_result["slow_calls"],
            ),
            (
                {action: float(action in ("repair", "execute")) for action in ACTIONS},
                5.0,
                1.0,
                1.0,
            ),
        )

    def test_every_candidate_forecast_matches_complete_exact_policy_evaluation(self):
        for risk in (0.0, 0.7):
            profile = Profile(risk=risk, discount_per_second=0.8)
            fast = fixture_fast(profile, ("repair", "recall", "execute"))
            for variable in (False, True):
                scenario = Scenario(
                    deadline=10, budget=12, horizon=4, variable_time=variable
                )
                root = initial_state(scenario)
                new = OneSlowControllerV2(scenario, root, profile, fast)
                decision = new.choose(scenario, root)
                self.assertTrue(new.forecast.complete)
                self.assertEqual(len(new.forecast.root_action_values), len(ACTIONS))
                for action, prediction in new.forecast.root_action_values:
                    with self.subTest(risk=risk, variable=variable, action=action):
                        forced = ForcedRootThenFast(
                            root, profile, fast, replace(decision, action=action)
                        )
                        result = evaluate(scenario, profile, forced)
                        self.assertAlmostEqual(prediction, result["value"], places=12)
                        self.assertEqual(result["budget_violations"], 0)
                        self.assertEqual(result["slow_calls"], 1)

    def test_every_reachable_successor_uses_fast_actions_and_fast_fees(self):
        profile = Profile(risk=0.7, discount_per_second=0.8)
        scenario = Scenario(deadline=10, budget=12, horizon=4)
        root = initial_state(scenario)
        fast = fixture_fast(profile, ("repair", "recall", "execute"))
        new = OneSlowControllerV2(scenario, root, profile, fast)
        decision = new.choose(scenario, root)
        admitted = after_compute(root, decision)
        direct_fast = Controller("fast", profile, fast)
        pending, seen = deque(), set()
        for action, _ in new.forecast.root_action_values:
            pending.extend(
                outcome.next_state
                for outcome in transitions(scenario, admitted, action)
                if outcome.next_state is not None
            )
        while pending:
            state = pending.popleft()
            if state in seen:
                continue
            seen.add(state)
            actual = new.choose(scenario, state)
            self.assertEqual(actual, direct_fast.choose(scenario, state))
            self.assertNotEqual(actual.route, "slow")
            pending.extend(
                outcome.next_state
                for outcome in transitions(
                    scenario, after_compute(state, actual), actual.action
                )
                if outcome.next_state is not None
            )
        self.assertGreater(len(seen), 20)

    def test_full_horizon_keeps_a_real_fourth_fast_action(self):
        profile = Profile(risk=0.7, discount_per_second=0.8)
        scenario = Scenario(deadline=10, budget=16, horizon=4, variable_time=False)
        root = initial_state(scenario)
        fast = fixture_fast(profile, ("repair", "recall", "execute"))
        new = OneSlowControllerV2(scenario, root, profile, fast)
        decision = new.choose(scenario, root)
        self.assertTrue(new.forecast.complete)
        prediction = dict(new.forecast.root_action_values)["observe"]
        forced = ForcedRootThenFast(
            root, profile, fast, replace(decision, action="observe")
        )
        result = evaluate(scenario, profile, forced)
        self.assertAlmostEqual(prediction, result["value"], places=12)
        self.assertEqual(result["actions"]["execute"], 1.0)
        self.assertEqual(result["decision_calls"], 4.0)
        truncated = Search(
            scenario, profile, 96, owner=Controller("fast", profile, fast)
        ).q(after_compute(root, decision), "observe", 3)
        truncated = -profile.resource_weight * decision.cost + edge_value(
            decision.duration, truncated, profile
        )
        self.assertGreater(abs(prediction - truncated), 1e-4)

    def test_nonadditive_utility_uses_nested_branches_instead_of_flattened_paths(self):
        scenario = Scenario(budget=10, horizon=2)
        root = initial_state(scenario)
        differences = []
        for risk in (0.0, 0.7):
            profile = Profile(risk=risk, discount_per_second=0.8)
            fast = fixture_fast(profile)
            new = OneSlowControllerV2(scenario, root, profile, fast)
            decision = new.choose(scenario, root)
            self.assertTrue(new.forecast.complete)
            forced = ForcedRootThenFast(
                root, profile, fast, replace(decision, action="observe")
            )
            result = evaluate(scenario, profile, forced)
            prediction = dict(new.forecast.root_action_values)["observe"]
            self.assertAlmostEqual(prediction, result["value"], places=12)
            lottery = path_lottery(scenario, profile, forced, root)
            flattened = certainty_equivalent(
                [value for _, value in lottery],
                [float(mass) for mass, _ in lottery],
                profile.risk,
            )
            differences.append(abs(flattened - prediction))
        self.assertLess(differences[0], 1e-12)
        self.assertGreater(differences[1], 1e-4)

    def test_incomplete_root_comparison_keeps_fee_and_discards_partial_scores(self):
        profile, scenario = Profile(), Scenario(budget=10)
        root, fast = initial_state(scenario), fixture_fast(profile)
        new = OneSlowControllerV2(scenario, root, profile, fast, node_limit=1)
        decision = new.choose(scenario, root)
        self.assertEqual(
            decision,
            Decision("execute", 2, 1, 1, 1, True, "slow"),
        )
        self.assertFalse(new.forecast.complete)
        self.assertEqual(new.forecast.root_action_values, ())
        episode = sample_episode(scenario, profile, new, 7)
        self.assertEqual(
            (episode["controller_cost"], episode["budget_violations"]), (2, 0)
        )

    def test_retained_snapshot_does_not_follow_caller_mutation(self):
        profile, scenario = Profile(), Scenario(budget=10, horizon=2)
        fast, root = fixture_fast(profile), initial_state(scenario)
        expected_identity = fast.record()["checkpoint_sha256"]
        new = OneSlowControllerV2(scenario, root, profile, fast)
        before = new.choose(scenario, root), new.forecast
        fast.actor[ACTIONS.index("stop")][0] = 8.0
        fast.training["changed_by_caller"] = True
        self.assertEqual((new.choose(scenario, root), new.forecast), before)
        self.assertEqual(new.fast_checkpoint_sha256, expected_identity)
        with self.assertRaises(ValueError):
            new.choose(replace(scenario, stop_reward=0.9), root)
        with self.assertRaises(ValueError):
            OneSlowControllerV2(scenario, root, replace(profile, risk=0), fast)
        new.learner.actor[ACTIONS.index("stop")][0] = 8.0
        with self.assertRaises(ValueError):
            new.choose(scenario, root)

    def test_admission_and_emergency_preserve_hard_budgets(self):
        profile = Profile()
        fast = fixture_fast(profile)
        for scenario in (
            Scenario(budget=0),
            Scenario(budget=1),
            Scenario(budget=3),
            Scenario(deadline=0),
            Scenario(horizon=0),
        ):
            with self.subTest(scenario=scenario):
                root = initial_state(scenario)
                new = OneSlowControllerV2(scenario, root, profile, fast)
                charge = Controller("mpc", profile, fast).compute_charge(root)
                decision = new.choose(scenario, root)
                self.assertEqual(
                    (decision.cost, decision.duration, decision.route),
                    (charge.cost, charge.duration, charge.route),
                )
                self.assertIsNone(new.forecast)
                episode = sample_episode(scenario, profile, new, 23)
                self.assertLessEqual(
                    episode["controller_cost"] + episode["environment_cost"],
                    scenario.budget,
                )
                self.assertLessEqual(episode["duration_seconds"], scenario.deadline)
                self.assertEqual(episode["budget_violations"], 0)

    def test_remaining_root_does_not_receive_an_invented_credit_refund(self):
        profile, scenario = Profile(), Scenario(budget=10, horizon=3)
        root = replace(initial_state(scenario), budget_left=3, steps_left=1)
        new = OneSlowControllerV2(scenario, root, profile, fixture_fast(profile))
        decision = new.choose(scenario, root)
        self.assertEqual(
            (decision.cost, decision.duration, decision.route), (1, 0, "fast")
        )
        self.assertEqual(after_compute(root, decision).budget_left, 2)
        result = evaluate(scenario, profile, new, start_state=root)
        self.assertEqual((result["controller_cost"], result["slow_calls"]), (1.0, 0.0))


if __name__ == "__main__":
    unittest.main()
