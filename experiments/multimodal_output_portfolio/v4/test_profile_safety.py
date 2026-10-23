"""Adversarial source-level guards for finite NDU v4 control admission.

These tests do not attest scientific efficacy, natural-media generation,
target-hardware costs, or a deployable stochastic control policy.
"""
import math
import unittest

from portfolio import Config, Controller, State, conditional_ce, execute


class FiniteProfileSafetyTests(unittest.TestCase):
    def test_physical_budget_fields_reject_bool_float_and_out_of_range(self):
        bad = (
            ("horizon", False),
            ("horizon", 1.5),
            ("horizon", 4),
            ("max_units_per_step", 2.5),
            ("max_units_per_step", 0),
            ("unit_cost", True),
            ("unit_cost", 1.0),
            ("unit_cost", 0),
            ("unit_cost", 10**400),
            ("activation_cost", False),
            ("activation_cost", 0.5),
            ("activation_cost", -1),
            ("emission_cost_each", 0.5),
            ("emission_cost_each", 0),
            ("sync_penalty", 1.5),
            ("sync_penalty", -1),
            ("sync_penalty", 1_000_001),
        )
        for field, value in bad:
            with self.subTest(field=field, value=str(value)[:40]):
                with self.assertRaises(ValueError):
                    Config(**{field: value})

    def test_risk_and_price_reject_nan_infinity_bool_and_unbounded(self):
        for field in ("risk_aversion", "cost_shadow_price"):
            for value in (float("nan"), float("inf"), float("-inf"),
                          -0.1, True, "0.1", 10**400):
                with self.subTest(field=field, value=str(value)[:30]):
                    with self.assertRaises(ValueError):
                        Config(**{field: value})
        with self.assertRaises(ValueError):
            Config(risk_aversion=10.1)
        with self.assertRaises(ValueError):
            Config(cost_shadow_price=1_000_000.1)
        self.assertEqual(Config(activation_cost=0, risk_aversion=0,
                                cost_shadow_price=0).emission_reserve, 4)

    def test_zero_mass_outlier_cannot_underflow_lawful_risk(self):
        # Before this correction, the impossible -1e6 branch became the
        # stabilization anchor and exp(-1_000_003) underflowed to zero.
        for gamma in (0, 0.25, 1, 10):
            with self.subTest(gamma=gamma):
                self.assertAlmostEqual(
                    conditional_ce((-1e6, 3), (0, 1), gamma), 3.0)
                self.assertAlmostEqual(
                    conditional_ce((3, -1e6), (1, 0), gamma), 3.0)
                self.assertAlmostEqual(
                    conditional_ce((-1e12, 1e12), (0, 1), gamma), 1e12)

    def test_zero_probability_outcome_is_invariant_to_its_value(self):
        for gamma in (0, 0.5, 10):
            baseline = conditional_ce((10, 20), (0.5, 0.5), gamma)
            for impossible in (-1e12, -1e6, 0, 1e12):
                with self.subTest(gamma=gamma, impossible=impossible):
                    self.assertAlmostEqual(
                        conditional_ce((10, impossible, 20),
                                       (0.5, 0.0, 0.5), gamma),
                        baseline)

    def test_conditional_risk_law_rejects_ambiguous_probabilities(self):
        bad = (
            ((2, 3), (0, 0), 0.5),
            ((2, 3), (0.5, 0.5000000001), 0.5),
            ((2, 3), (True, 0), 0.5),
            ((2, 3), (float("nan"), 1), 0.5),
            ((2, 3), (0.5, 10**400), 0.5),
            ((2, 3), (-0.1, 1.1), 0.5),
            ((2, 3), (0.5, 0.5), float("nan")),
            ((2, 3), (0.5, 0.5), True),
            ((2, 3), (0.5, 0.5), 10**400),
            ((2, 10**400), (0.5, 0.5), 0.5),
            ((2, float("inf")), (0.5, 0.5), 0.5),
        )
        for values, probabilities, gamma in bad:
            with self.subTest(values=str(values)[:50],
                              probabilities=str(probabilities)[:50],
                              gamma=str(gamma)[:20]):
                with self.assertRaises(ValueError):
                    conditional_ce(values, probabilities, gamma)

    def test_unchanged_original_causal_trajectory_and_finite_receipts(self):
        cfg = Config(horizon=3, risk_aversion=0, activation_cost=1,
                     cost_shadow_price=0.02)
        initial = State((0, 0, 0, 0), 12)
        a = execute(initial, cfg, seed=0)
        b = execute(initial, cfg, seed=0)
        self.assertEqual(a, b)
        self.assertEqual(
            [row["allocation"] for row in a["records"]
             if any(row["allocation"])],
            [(0, 0, 1, 1), (0, 1, 0, 0), (1, 0, 0, 0)])
        self.assertTrue(all(math.isfinite(row["estimated_value"])
                            for row in a["records"]))
        self.assertEqual(a["spent"] + a["remaining_after_emission"], 12)
        self.assertEqual(a["scope"], "RESEARCH_ONLY_DENY_ALL")
        self.assertTrue(math.isfinite(Controller(cfg).solve(initial)[1]))


if __name__ == "__main__":
    unittest.main()
