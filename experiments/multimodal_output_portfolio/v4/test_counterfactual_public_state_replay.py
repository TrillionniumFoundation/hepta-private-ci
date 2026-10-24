"""Fail-closed public-state action replay for finite counterfactual evaluation.

These are synthetic source contract checks, not natural four-modal evidence.
"""
import unittest

from counterfactual_audit import evaluate, evaluate_dependence
from portfolio import Allocation, Config, State, STOP


class CounterfactualPublicStateReplayTests(unittest.TestCase):
    def setUp(self):
        self.initial = State((0, 0, 0, 0), 12)
        self.cfg = Config(horizon=1, activation_cost=5, risk_aversion=0)
        self.refine = Allocation((1, 0, 0, 0))
        self.regime = (((0, 0, 0, 0), 0.5), ((1, 1, 1, 1), 0.5))

    def alternating_policy(self):
        calls = [0]

        def choose(state):
            if state.step:
                return STOP
            calls[0] += 1
            return STOP if calls[0] % 2 else self.refine

        return choose

    def test_nominal_replay_rejects_alternating_first_action(self):
        # Every positive-probability path starts in the same public state.
        # Without a guard, STOP and REFINE are silently mixed as one policy.
        with self.assertRaisesRegex(ValueError, "non-deterministic public-state"):
            evaluate(self.initial, self.cfg, self.alternating_policy())

    def test_dependence_replay_rejects_alternating_first_action(self):
        with self.assertRaisesRegex(ValueError, "non-deterministic public-state"):
            evaluate_dependence(self.initial, self.cfg,
                                self.alternating_policy(), self.regime)

    def test_repeated_identical_public_decisions_remain_admitted(self):
        def choose(state):
            return self.refine if state.step == 0 else STOP

        nominal = evaluate(self.initial, self.cfg, choose)
        shifted = evaluate_dependence(self.initial, self.cfg,
                                      choose, self.regime)
        self.assertEqual(nominal["mean_paid_units"], 10)
        self.assertEqual(shifted["mean_paid_units"], 10)
        self.assertTrue(nominal["all_budget_feasible"])
        self.assertTrue(shifted["all_budget_feasible"])


if __name__ == "__main__":
    unittest.main()
