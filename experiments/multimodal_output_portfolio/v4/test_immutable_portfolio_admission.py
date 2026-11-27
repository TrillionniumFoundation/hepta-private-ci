"""Fail closed on mutable public-state and action containers.

Synthetic API invariants only; no natural observation or physical cost claim.
A frozen dataclass does not freeze a list passed into one of its fields.
"""
import unittest

from counterfactual_audit import evaluate
from portfolio import Allocation, Config, State, STOP


class ImmutablePortfolioAdmissionTests(unittest.TestCase):
    def test_mutable_observation_container_cannot_enter_public_state(self):
        levels = [0, 0, 0, 0]
        with self.assertRaisesRegex(ValueError, "invalid public portfolio state"):
            State(levels, 12)
        # A previously accepted list could mutate after validation, changing
        # Bellman cache keys or making state replay non-reproducible.
        levels[0] = 2

    def test_mutable_action_cannot_enter_policy_or_cost_ledger(self):
        units = [1, 0, 0, 0]
        with self.assertRaisesRegex(ValueError, "invalid four-channel allocation"):
            Allocation(units)
        units[0] = 0

    def test_non_tuple_iterable_is_not_an_immutable_proof(self):
        class MutableFour:
            def __init__(self):
                self.values = [0, 0, 0, 0]
            def __len__(self):
                return 4
            def __iter__(self):
                return iter(self.values)
        candidate = MutableFour()
        with self.assertRaisesRegex(ValueError, "invalid public portfolio state"):
            State(candidate, 12)
        with self.assertRaisesRegex(ValueError, "invalid four-channel allocation"):
            Allocation(candidate)

    def test_legitimate_tuple_policy_and_four_outputs_remain_valid(self):
        initial = State((0, 0, 0, 0), 12)
        cfg = Config(horizon=1, activation_cost=5, risk_aversion=0)
        active = Allocation((1, 0, 0, 0))
        self.assertEqual(hash(initial), hash(State((0, 0, 0, 0), 12)))
        self.assertEqual(hash(active), hash(Allocation((1, 0, 0, 0))))
        report = evaluate(initial, cfg,
                          lambda state: active if state.step == 0 else STOP)
        self.assertTrue(report["complete_outputs"])
        self.assertTrue(report["all_budget_feasible"])
        self.assertEqual(report["mean_paid_units"], 10)


if __name__ == "__main__":
    unittest.main()
