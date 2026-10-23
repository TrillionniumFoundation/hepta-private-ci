"""Executed synthetic tests for jointly budgeted evidence and four outputs.

No test imports hidden truth into a live control state. The independent path
audit computes terminal outcomes under both the admitted and shifted channels.
"""
import unittest
from fractions import Fraction

from joint_portfolio import (
    Profile, PublicState, Refine, QUERY, STOP, JointController,
    legal_actions, witness_probability, observe_witness, observe_refinement,
    terminal_external_loss, emission, independent_path_audit, conditional_ce,
)


class JointPortfolioTests(unittest.TestCase):
    def setUp(self):
        self.cfg = Profile(horizon=3, gamma=0.7, shadow_price=0.03)

    def test_bellman_value_matches_full_truth_and_witness_paths(self):
        for prior in (Fraction(1, 2), Fraction(99, 100)):
            state = PublicState((0, 0, 0, 0), prior, 12)
            controller = JointController(self.cfg)
            policy = lambda s: controller.solve(s)[0]
            expected = controller.solve(state)[1]
            external = independent_path_audit(state, self.cfg, policy)
            self.assertAlmostEqual(expected, external["risk_utility"], places=9)
            self.assertTrue(external["all_four_outputs"])
            self.assertTrue(external["all_funded"])
            self.assertGreaterEqual(
                external["fractional_cvar90"], external["mean_loss"]
            )

    def test_evidence_and_refinement_compete_with_emission_reserve(self):
        state = PublicState((1, 0, 0, 0), Fraction(1, 2), 5)
        self.assertIn(QUERY, legal_actions(state, self.cfg))
        after = observe_witness(state, 0, self.cfg)
        self.assertEqual(after.remaining, 4)
        self.assertEqual(after.stage, 1)
        self.assertEqual(legal_actions(after, self.cfg), (STOP,))
        self.assertNotIn(QUERY, legal_actions(after, self.cfg))
        self.assertEqual(
            set(emission(after)), {"text", "audio", "image", "video"}
        )

    def test_private_truth_not_available_at_decision(self):
        state = PublicState((2, 2, 2, 2), Fraction(1, 2), 7)
        self.assertEqual(
            witness_probability(state, 0, self.cfg), Fraction(1, 2)
        )
        self.assertEqual(
            observe_witness(state, 0, self.cfg).p_truth_zero,
            Fraction(49, 50),
        )
        self.assertEqual(
            observe_witness(state, 1, self.cfg).p_truth_zero,
            Fraction(1, 50),
        )
        self.assertNotIn("truth", vars(state))

    def test_four_agreeing_modalities_can_all_be_factually_wrong(self):
        state = PublicState((2, 2, 2, 2), Fraction(1, 2), 5)
        self.assertEqual(terminal_external_loss(emission(state), 0, self.cfg), 0)
        self.assertEqual(terminal_external_loss(emission(state), 1, self.cfg), 8)
        output = emission(state)
        output.pop("video")
        with self.assertRaises(ValueError):
            terminal_external_loss(output, 0, self.cfg)

    def test_observed_shock_changes_next_modality_allocation(self):
        cfg = Profile(horizon=3, gamma=0, shadow_price=0.01,
                      factual_error_cost=1)
        controller = JointController(cfg)
        state = PublicState((0, 0, 0, 0), Fraction(99, 100), 12)
        initial, _ = controller.solve(state)
        self.assertIsInstance(initial, Refine)
        failed = observe_refinement(state, initial, 0, cfg)
        improved = observe_refinement(state, initial, 2, cfg)
        self.assertNotEqual(failed.levels, improved.levels)
        self.assertNotEqual(controller.solve(failed)[0],
                            controller.solve(improved)[0])

    def test_hard_query_is_valuable_easy_query_is_not(self):
        cfg = Profile(horizon=2, gamma=1, shadow_price=0.02,
                      factual_error_cost=32)
        hard = PublicState((2, 2, 2, 2), Fraction(1, 2), 5)
        easy = PublicState((2, 2, 2, 2), Fraction(99, 100), 5)
        self.assertEqual(JointController(cfg).solve(hard)[0], QUERY)
        self.assertEqual(JointController(cfg).solve(easy)[0], STOP)

    def test_impossible_extreme_branch_does_not_poison_utility(self):
        self.assertAlmostEqual(conditional_ce((-1e7, 1), (0, 1), 10), 1)

    def test_forged_budget_and_config_rejected(self):
        with self.assertRaises(ValueError):
            Profile(witness_cost=0)
        with self.assertRaises(ValueError):
            Profile(gamma=float("nan"))
        with self.assertRaises(ValueError):
            Profile(horizon=True)
        with self.assertRaises(ValueError):
            legal_actions(PublicState((0, 0, 0, 0), Fraction(1, 2), 3),
                          self.cfg)


class EvidenceDistributionShiftTests(unittest.TestCase):
    def test_frozen_98_percent_witness_fails_when_channel_is_reversed(self):
        cfg = Profile(horizon=2, gamma=1, shadow_price=0.02,
                      factual_error_cost=32)
        state = PublicState((2, 2, 2, 2), Fraction(1, 2), 5)
        controller = JointController(cfg)
        policy = lambda s: controller.solve(s)[0]
        self.assertEqual(policy(state), QUERY)
        nominal = independent_path_audit(state, cfg, policy)
        shifted = independent_path_audit(
            state, cfg, policy, actual_witness_accuracy=Fraction(1, 50)
        )
        no_query = independent_path_audit(state, cfg, lambda _: STOP)
        self.assertLess(nominal["mean_loss"], no_query["mean_loss"])
        self.assertGreater(shifted["mean_loss"], no_query["mean_loss"])
        self.assertLess(shifted["risk_utility"], no_query["risk_utility"])
        self.assertEqual(shifted["fractional_cvar90"], 32.0)

    def test_actual_evidence_law_is_not_controller_assumption(self):
        cfg = Profile(horizon=2)
        state = PublicState((2, 2, 2, 2), Fraction(1, 2), 5)
        with self.assertRaises(ValueError):
            independent_path_audit(
                state, cfg, lambda _: STOP, actual_witness_accuracy=1.0
            )


class BoundedSolverCostTests(unittest.TestCase):
    def test_budget_exhaustion_returns_explicit_nonoptimal_safe_stop(self):
        from joint_portfolio import SolverBudgetExceeded
        cfg = Profile(horizon=3)
        state = PublicState((0, 0, 0, 0), Fraction(1, 2), 12)
        limited = JointController(cfg, max_expansions=1)
        with self.assertRaises(SolverBudgetExceeded):
            limited.solve(state)
        action, value, disposition = limited.select_with_fallback(state)
        self.assertEqual(action, STOP)
        self.assertEqual(disposition, "BUDGETED_STOP_FALLBACK")
        self.assertEqual(value, limited.terminal(state))
        self.assertEqual(limited.value_expansions, 1)

    def test_sufficient_budget_reports_exact_finite_scope_only(self):
        cfg = Profile(horizon=1)
        state = PublicState((2, 2, 2, 2), Fraction(99, 100), 5)
        controller = JointController(cfg, max_expansions=100000)
        action, _, disposition = controller.select_with_fallback(state)
        self.assertEqual(action, STOP)
        self.assertEqual(disposition, "EXACT_FINITE_VALUE")
        self.assertGreaterEqual(controller.value_expansions, 1)
        self.assertLessEqual(controller.value_expansions, controller.max_expansions)
        with self.assertRaises(ValueError):
            JointController(cfg, max_expansions=False)


if __name__ == "__main__":
    unittest.main()
