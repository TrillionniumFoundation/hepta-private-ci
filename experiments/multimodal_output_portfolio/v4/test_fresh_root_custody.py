"""Source-only modeled-budget custody at the v4 episode entry boundary.

Neither these checks nor the independent fixture constitute real hardware
metering, a real witness, or natural model scientific qualification.
"""
import unittest
from fractions import Fraction

from portfolio import Allocation, Config, State, advance, charge
from joint_evidence_generation import (
    EMIT, JointState, full_outcome_audit, query_successor,
)


class FreshRootCustodyTests(unittest.TestCase):
    def setUp(self):
        self.cfg = Config(activation_cost=5, risk_aversion=0)

    def test_root_cannot_forge_paid_activation(self):
        root = State((0, 0, 0, 0), 12)
        action = Allocation((1, 0, 0, 0))
        self.assertEqual(charge(root, action, self.cfg), 6)
        # Previously active_mask=1 at step=0 waived the modeled 5-unit
        # activation cost; no transition or receipt had paid for it.
        for mask in (1, 5, 15):
            with self.subTest(mask=mask):
                with self.assertRaisesRegex(ValueError, "invalid public portfolio state"):
                    State((0, 0, 0, 0), 12, step=0, active_mask=mask)

    def test_root_cannot_claim_unpaid_independent_witness(self):
        with self.assertRaisesRegex(ValueError, "unsupported public belief-state"):
            JointState(State((0, 0, 0, 0), 12), Fraction(1, 2), True)

    def test_true_successors_retain_earned_state(self):
        root = State((0, 0, 0, 0), 12)
        continuation = advance(root, Allocation((1, 0, 0, 0)), 2, self.cfg)
        self.assertEqual((continuation.step, continuation.active_mask, continuation.remaining),
                         (1, 1, 6))
        purchased = query_successor(JointState(root, Fraction(1, 2)), self.cfg, 0)
        self.assertEqual(purchased.generation.step, 1)
        self.assertTrue(purchased.witness_seen)
        self.assertEqual(purchased.generation.remaining, 11)

    def test_fresh_root_remains_eligible_for_four_output_audit(self):
        root = JointState(State((2, 2, 2, 2), 4), Fraction(1, 2))
        report = full_outcome_audit(root, self.cfg, lambda _state: EMIT)
        self.assertTrue(report["four_outputs_emitted"])
        self.assertEqual(report["budget_violations"], 0)
        self.assertEqual(report["mean_modeled_cost"], 4)


if __name__ == "__main__":
    unittest.main()
