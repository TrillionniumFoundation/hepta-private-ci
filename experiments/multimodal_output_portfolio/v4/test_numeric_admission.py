"""Adversarial scientific admission tests for finite NDU portfolio values.

All fixtures are synthetic. These tests catch ill-typed physical budgets,
false probability normalization and an impossible low-payoff branch that
previously caused log-sum-exp underflow and a failed control decision.
"""
import math
import unittest

from portfolio import Config, Controller, State, conditional_ce


class NumericAdmissionTests(unittest.TestCase):
    def test_zero_probability_extreme_is_not_part_of_conditional_support(self):
        # Original implementation anchored at -1e6, even with p=0, so every
        # supported exponential underflowed and the control failed closed.
        for values, probabilities in (
            ((-1_000_000.0, 2.5), (0.0, 1.0)),
            ((2.5, -1_000_000.0), (1.0, 0.0)),
        ):
            with self.subTest(values=values):
                self.assertEqual(conditional_ce(values, probabilities, 10.0), 2.5)
                self.assertEqual(conditional_ce(values, probabilities, 0), 2.5)

    def test_support_permutation_and_impossible_outcome_invariance(self):
        for gamma in (0, 0.1, 1, 10):
            a = conditional_ce((1.5, 3.5), (0.4, 0.6), gamma)
            b = conditional_ce((-1e9, 3.5, 1.5), (0.0, 0.6, 0.4), gamma)
            self.assertAlmostEqual(a, b, places=12)

    def test_tiny_supported_probability_is_not_silently_dropped(self):
        actual = conditional_ce((-1000.0, 4.0), (1e-300, 1.0 - 1e-300), 1.0)
        self.assertTrue(math.isfinite(actual))
        self.assertLess(actual, 4.0)

    def test_invalid_normalization_beyond_absolute_tolerance_rejects(self):
        with self.assertRaisesRegex(ValueError, "conditional risk law"):
            conditional_ce((0.0, 1.0), (0.5, 0.5000000005), 1.0)

    def test_exact_zero_mass_law_is_rejected(self):
        with self.assertRaises(ValueError):
            conditional_ce((2.0, 3.0), (0.0, 0.0), 2.0)

    def test_budget_horizon_and_sync_units_are_exact_integers(self):
        for keyword, value in (
            ("horizon", 1.5),
            ("horizon", True),
            ("max_units_per_step", 1.5),
            ("unit_cost", 1.5),
            ("unit_cost", True),
            ("activation_cost", 0.5),
            ("emission_cost_each", True),
            ("sync_penalty", float("nan")),
            ("sync_penalty", 1.5),
        ):
            with self.subTest(keyword=keyword, value=value):
                with self.assertRaisesRegex(ValueError, "control profile"):
                    Config(**{keyword: value})

    def test_risk_and_shadow_prices_reject_bools_nonfinite_and_strings(self):
        for keyword, value in (
            ("risk_aversion", True),
            ("risk_aversion", float("nan")),
            ("risk_aversion", "1"),
            ("cost_shadow_price", True),
            ("cost_shadow_price", float("inf")),
            ("cost_shadow_price", float("nan")),
            ("cost_shadow_price", "0.1"),
        ):
            with self.subTest(keyword=keyword, value=value):
                with self.assertRaisesRegex(ValueError, "control profile"):
                    Config(**{keyword: value})

    def test_valid_zero_risk_profile_preserves_solver_and_budget(self):
        cfg = Config(horizon=2, risk_aversion=0, cost_shadow_price=0.02)
        state = State((0, 0, 0, 0), 12)
        allocation, value = Controller(cfg).solve(state)
        self.assertEqual(len(allocation.units), 4)
        self.assertTrue(math.isfinite(value))


if __name__ == "__main__":
    unittest.main()
