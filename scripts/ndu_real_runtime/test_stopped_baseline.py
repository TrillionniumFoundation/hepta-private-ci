"""Behavioral equivalence and dependence-sensitive ordinary-control checks."""

import unittest

from .controllers import ControlPlan
from .stopped_baseline import compare_ordinary_risk, ordinary_risk_choice
from .stopped_control import StoppedController
from .test_stopped_control import Centers, bank, record, state


class OrdinaryRiskTests(unittest.TestCase):
    def test_same_marginals_different_joint_law_reverse_risk_choice(self):
        paired = {
            "STOP": ((0.2, 1.0, 1.0),),
            "WRITE_TEXT": ((0.22, 1.0, 0.5), (0.82, 7.0, 0.5)),
        }
        factorized = dict(
            paired,
            WRITE_TEXT=tuple(
                (quality, seconds, 0.25)
                for quality in (0.22, 0.82)
                for seconds in (1.0, 7.0)
            ),
        )
        plan = ControlPlan(horizon=1, risk=10, latency_weight=0.1)
        self.assertEqual(ordinary_risk_choice(paired, plan)[0], "WRITE_TEXT")
        self.assertEqual(ordinary_risk_choice(factorized, plan)[0], "STOP")
        neutral = ControlPlan(horizon=1, risk=0, latency_weight=0.1)
        self.assertAlmostEqual(
            ordinary_risk_choice(paired, neutral)[1]["WRITE_TEXT"],
            ordinary_risk_choice(factorized, neutral)[1]["WRITE_TEXT"],
        )

    def test_degenerate_lottery_matches_all_risks_without_independent_gain(self):
        law = bank(
            [
                record(group, action, quality, seconds)
                for group in ("c1", "c2")
                for action, quality, seconds in (
                    ("STOP", 0.5, 1),
                    ("WRITE_TEXT", 0.7, 2),
                )
            ]
        )
        for risk in (0.0, 1e-20, 0.25, 40.0, 1000.0):
            plan = ControlPlan(horizon=1, particles=2, risk=risk)
            chosen, receipt = StoppedController(
                Centers(), law, plan, clock=lambda: 0
            ).choose(state("WRITE_TEXT"))
            comparison = compare_ordinary_risk(receipt, plan)
            self.assertEqual(chosen, "WRITE_TEXT")
            self.assertTrue(comparison["selected_action_equal"])
            self.assertTrue(comparison["values_equal_within_1e12"])
            self.assertEqual(comparison["additional_forecast_calls"], 0)
            self.assertFalse(comparison["independent_ndu_benefit_established"])

    def test_zero_risk_accounts_for_paid_stop(self):
        outcomes = {"STOP": ((0.6, 10, 1),), "WRITE_TEXT": ((0.55, 1, 1),)}
        action, scores = ordinary_risk_choice(outcomes, ControlPlan(horizon=1, risk=0))
        self.assertEqual(action, "WRITE_TEXT")
        self.assertAlmostEqual(scores["STOP"], 0.5)
        self.assertAlmostEqual(scores["WRITE_TEXT"], 0.54)

    def test_measured_budget_cut_and_practical_margin_are_shared(self):
        law = bank(
            [
                record(group, action, quality, seconds)
                for group in ("c1", "c2")
                for action, quality, seconds in (
                    ("STOP", 0.2, 1),
                    ("WRITE_TEXT", 0.9, 4),
                )
            ]
        )
        plan = ControlPlan(horizon=1, particles=2, risk=0.5)
        clock = iter((0.0, 2.0, 2.1))
        _, receipt = StoppedController(
            Centers(), law, plan, clock=lambda: next(clock)
        ).choose(state("WRITE_TEXT", remaining=5))
        self.assertEqual(receipt["over_budget_actions"], ["WRITE_TEXT"])
        self.assertEqual(
            compare_ordinary_risk(receipt, plan)["ordinary_action"], "STOP"
        )
        _, receipt = StoppedController(
            Centers(), law, plan, practical_margin=0.8, clock=lambda: 0
        ).choose(state("WRITE_TEXT"))
        self.assertEqual(
            compare_ordinary_risk(receipt, plan)["ordinary_action"], "STOP"
        )

    def test_invalid_lotteries_and_missing_stop_are_refused(self):
        plan = ControlPlan(horizon=1)
        for outcomes in (
            {"WRITE_TEXT": ((0.5, 1, 1),)},
            {"STOP": ((0.5, 1, 0.1),)},
            {"STOP": ((0.5, float("nan"), 1),)},
            {"STOP": ((True, 1, 1),)},
        ):
            with self.assertRaises(ValueError):
                ordinary_risk_choice(outcomes, plan)


if __name__ == "__main__":
    unittest.main()
