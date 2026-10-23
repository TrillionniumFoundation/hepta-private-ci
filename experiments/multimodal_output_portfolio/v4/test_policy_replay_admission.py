"""Prevent time-dependent / hidden-world policy actions laundering audit evidence.

No natural media, trained model, trusted observer, or production permission is
tested here: this is a synthetic causal replay contract regression.
"""
import unittest
from portfolio import Config
from joint_evidence_generation import (
    EMIT, QUERY, full_outcome_audit, mode_state,
)


class PolicyReplayAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.cfg = Config(horizon=2, cost_shadow_price=0.05, risk_aversion=1)
        self.initial = mode_state("hard", (2, 2, 0, 0), 10)

    def test_declared_query_cannot_mask_actual_emit(self):
        # Old audit called choose(initial) for first_action, then called it
        # again to execute; an impure caller could claim a QUERY without
        # paying for it. A checksum of the emitted outputs cannot catch this.
        calls = 0

        def dishonest(state):
            nonlocal calls
            if state == self.initial:
                calls += 1
                return QUERY if calls == 1 else EMIT
            return EMIT

        with self.assertRaisesRegex(ValueError, "public-state policy replay"):
            full_outcome_audit(self.initial, self.cfg, dishonest)
        self.assertEqual(calls, 2)

    def test_identical_public_state_cannot_branch_on_private_world_order(self):
        # Two hidden-truth branches revisit the same public root. An impure
        # callback that silently changes action on the later branch violates
        # the declared state-feedback / no-hidden-truth information set.
        calls = 0

        def changing(state):
            nonlocal calls
            if state == self.initial:
                calls += 1
                return QUERY if calls == 3 else EMIT
            return EMIT

        with self.assertRaisesRegex(ValueError, "public-state policy replay"):
            full_outcome_audit(self.initial, self.cfg, changing)
        self.assertEqual(calls, 3)

    def test_true_public_state_policy_preserves_external_audit(self):
        receipt = full_outcome_audit(
            self.initial, self.cfg, lambda state: EMIT,
        )
        self.assertEqual(receipt["first_action"], EMIT)
        self.assertEqual(receipt["query_probability"], 0)
        self.assertEqual(receipt["mean_modeled_cost"], 4)
        self.assertEqual(receipt["budget_violations"], 0)
        self.assertTrue(receipt["four_outputs_emitted"])


if __name__ == "__main__":
    unittest.main()
