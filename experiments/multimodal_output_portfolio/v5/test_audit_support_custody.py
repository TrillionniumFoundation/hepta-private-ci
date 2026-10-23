"""Adversarial source-level v5 path-support and policy-custody checks.

Finite synthetic evidence only: this does NOT certify an independent real
witness, learned natural generation, physical metering or production authority.
"""
import unittest
from fractions import Fraction

from joint_portfolio import (
    Profile, PublicState, QUERY, STOP, independent_path_audit,
)


class SupportAndPolicyCustodyTests(unittest.TestCase):
    def setUp(self):
        self.cfg = Profile(horizon=2, gamma=1, shadow_price=0.02)
        # Both private truths have positive prior mass. Four perfect toy
        # generation proxies mean only fact correctness affects external loss.
        self.initial = PublicState(
            (2, 2, 2, 2), Fraction(1, 2), 5
        )

    def test_zero_mass_reports_do_not_fabricate_observed_support(self):
        def one_purchase(s):
            return STOP if s.witnessed else QUERY

        for actual, expected_loss in (
            (Fraction(1), 0),
            (Fraction(0), self.cfg.factual_error_cost),
        ):
            with self.subTest(actual_witness_accuracy=actual):
                result = independent_path_audit(
                    self.initial, self.cfg, one_purchase,
                    actual_witness_accuracy=actual,
                )
                # Two truth branches x one report each. The other two
                # truth-report outcomes have EXACTLY ZERO probability.
                self.assertEqual(result["support_paths"], 2)
                self.assertEqual(result["unique_traces"], 2)
                self.assertAlmostEqual(result["mean_loss"], expected_loss)
                self.assertAlmostEqual(
                    result["fractional_cvar90"], expected_loss
                )
                self.assertTrue(result["all_funded"])
                self.assertTrue(result["all_four_outputs"])

        nominal = independent_path_audit(
            self.initial, self.cfg, one_purchase
        )
        self.assertEqual(nominal["support_paths"], 4)

    def test_same_public_state_must_never_choose_by_private_loop_order(self):
        called = {}

        def illicit_stateful_policy(state):
            count = called.get(state, 0)
            called[state] = count + 1
            if state.stage == 0:
                # First private truth arm emits, second truth arm queries.
                # No public observation changed. The original auditor
                # accepted this covert truth/order-dependent control.
                return STOP if count == 0 else QUERY
            return STOP

        with self.assertRaisesRegex(
            ValueError, "inconsistent action for identical public state"
        ):
            independent_path_audit(
                self.initial, self.cfg, illicit_stateful_policy
            )

    def test_stable_public_policy_still_passes_independent_replay(self):
        stable = lambda state: STOP if state.witnessed else QUERY
        first = independent_path_audit(self.initial, self.cfg, stable)
        second = independent_path_audit(self.initial, self.cfg, stable)
        self.assertEqual(first, second)
        self.assertEqual(first["support_paths"], 4)

    def test_true_prior_boundary_does_not_expand_support(self):
        # Even without QUERY, a logically possible but zero-prior truth
        # must not count toward independently enumerated outcomes.
        state = PublicState((2, 2, 2, 2), Fraction(1), 4)
        result = independent_path_audit(state, self.cfg, lambda _: STOP)
        self.assertEqual(result["support_paths"], 1)
        self.assertEqual(result["mean_loss"], 0)


if __name__ == "__main__":
    unittest.main()
