"""Behavioral checks for the new controls and their hard-budget admission."""

from fractions import Fraction
import unittest

from ndu_ctrl1.evaluation import evaluate, sample_episode
from ndu_ctrl1.model import Profile, Scenario, initial_state
from ndu_ctrl1.policies import after_compute

from .rules import RuleController


class RulesTests(unittest.TestCase):
    def test_repair_executes_with_two_charged_decisions(self):
        scenario = Scenario(prior=Fraction(1, 3), budget=10, horizon=3)
        policy = RuleController("repair_then_execute", Profile())
        row = sample_episode(scenario, Profile(), policy, 17)
        self.assertEqual([x["action"] for x in row["path"]], ["repair", "execute"])
        self.assertEqual(row["controller_cost"], 2)
        self.assertEqual(policy.counters["forecast_calls"], 0)

    def test_emergency_stop_is_free_and_spends_no_forecasts(self):
        scenario = Scenario(budget=0)
        for rule in RuleController.RULES:
            with self.subTest(rule=rule):
                controller = RuleController(rule, Profile())
                row = evaluate(scenario, Profile(), controller)
                self.assertEqual(
                    (row["controller_cost"], row["actions"]["stop"]), (0, 1)
                )
                self.assertEqual(controller.counters["forecast_calls"], 0)

    def test_terminal_value_uses_cost_and_stop_alternative(self):
        for prior, expected in [
            (Fraction(1, 10), "stop"),
            (Fraction(9, 10), "execute"),
        ]:
            scenario = Scenario(prior=prior)
            controller = RuleController("terminal_value", Profile())
            decision = controller.choose(scenario, initial_state(scenario))
            self.assertEqual(
                (decision.action, decision.cost, decision.forecast_calls),
                (expected, 1, 2),
            )
            self.assertEqual(controller.counters["forecast_calls"], 2)

    def test_action_legality_uses_post_compute_budget(self):
        scenario = Scenario(budget=3)
        for rule in RuleController.RULES:
            decision = RuleController(rule, Profile()).choose(
                scenario, initial_state(scenario)
            )
            self.assertNotEqual(decision.action, "execute")
            self.assertEqual(
                after_compute(initial_state(scenario), decision).budget_left, 2
            )

    def test_last_step_never_wastes_repair(self):
        scenario = Scenario(horizon=1)
        decision = RuleController("repair_then_execute", Profile()).choose(
            scenario, initial_state(scenario)
        )
        self.assertEqual(decision.action, "execute")

    def test_sampled_rules_never_exceed_limits(self):
        for budget, deadline in [(1, 0), (3, 2), (6, 4), (10, 8)]:
            scenario = Scenario(budget=budget, deadline=deadline)
            for rule in RuleController.RULES:
                for seed in range(8):
                    row = sample_episode(
                        scenario, Profile(), RuleController(rule, Profile()), seed
                    )
                    self.assertLessEqual(
                        row["controller_cost"] + row["environment_cost"], budget
                    )
                    self.assertLessEqual(row["duration_seconds"], deadline)


if __name__ == "__main__":
    unittest.main()
