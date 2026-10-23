"""Model trajectory cost scope, not checkpoint authentication or metering."""
import unittest
from fractions import Fraction

from counterfactual_audit import evaluate, evaluate_dependence
from joint_evidence_generation import EMIT, JointState, full_outcome_audit
from portfolio import Allocation, Config, State, STOP, advance, charge, execute


class ExecuteBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.cfg = Config(activation_cost=5, max_units_per_step=1,
                          risk_aversion=0, cost_shadow_price=0)

    def test_supplied_state_changes_suffix_cost_not_provenance(self):
        fresh = execute(State((0, 2, 2, 2), 10), self.cfg, seed=0)
        supplied = execute(State((0, 2, 2, 2), 10, step=1, active_mask=1),
                           self.cfg, seed=0)
        self.assertEqual((fresh["spent"], supplied["spent"]), (10, 5))
        self.assertEqual((fresh["records"][0]["control_cost"],
                          supplied["records"][0]["control_cost"]), (6, 1))
        for receipt in (fresh, supplied):
            self.assertEqual(receipt["spent"], self.cfg.emission_reserve + sum(
                record["control_cost"] for record in receipt["records"]))
            self.assertEqual(receipt["spent"] + receipt["remaining_after_emission"],
                             10)

    def test_paid_successor_retains_activation_and_prefix_cost_is_separate(self):
        root = State((0, 2, 2, 2), 16)
        action = Allocation((1, 0, 0, 0))
        prefix_cost = charge(root, action, self.cfg)
        successor = advance(root, action, 0, self.cfg)
        self.assertEqual(successor, State((0, 2, 2, 2), 10, step=1, active_mask=1))
        receipt = execute(successor, self.cfg, seed=0)
        self.assertEqual((prefix_cost, receipt["spent"]), (6, 5))
        self.assertEqual(receipt["records"][0]["control_cost"], self.cfg.unit_cost)
        self.assertEqual(prefix_cost + receipt["spent"],
                         root.remaining - receipt["remaining_after_emission"])

    def test_full_episode_audits_reject_continuation_as_root(self):
        successor = advance(State((0, 2, 2, 2), 16),
                            Allocation((1, 0, 0, 0)), 0, self.cfg)
        with self.assertRaisesRegex(ValueError, "first decision boundary"):
            full_outcome_audit(JointState(successor, Fraction(1, 2)),
                               self.cfg, lambda _state: EMIT)
        with self.assertRaisesRegex(ValueError, "unfunded four-modal emission"):
            evaluate(successor, self.cfg, lambda _state: STOP)
        with self.assertRaisesRegex(ValueError, "noninitial four-modal emission"):
            evaluate_dependence(successor, self.cfg, lambda _state: STOP,
                                (((0, 0, 0, 0), 1.0),))


if __name__ == "__main__":
    unittest.main()
