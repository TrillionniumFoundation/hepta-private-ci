"""Supported-path preservation for the bounded float-only synthetic audit."""
from decimal import Decimal, localcontext
import unittest

from counterfactual_audit import (
    dependent_scenarios, evaluate, evaluate_dependence, fixed_plan_policy,
    scenarios,
)
from portfolio import Allocation, Config, State


class CounterfactualPathMassTests(unittest.TestCase):
    def test_scalar_supported_products_cannot_silently_disappear(self):
        for horizon, rare in ((2, 1e-200), (3, 1e-110)):
            for law in ((rare, 0., 1.), (1., rare, 0.), (0., 1., rare)):
                with self.subTest(horizon=horizon, law=law):
                    with self.assertRaisesRegex(ValueError, "positive path probability underflow"):
                        list(scenarios(horizon, law))

    def test_dependent_supported_products_cannot_silently_disappear(self):
        for horizon, rare in ((2, 1e-200), (3, 1e-110)):
            regime = (((0, 0, 0, 0), rare), ((2, 2, 2, 2), 1.))
            for ordered in (regime, tuple(reversed(regime))):
                with self.subTest(horizon=horizon, regime=ordered):
                    with self.assertRaisesRegex(ValueError, "positive path probability underflow"):
                        list(dependent_scenarios(horizon, ordered))

    def test_full_audits_reject_instead_of_omitting_rare_bad_tail(self):
        cfg = Config(horizon=2, activation_cost=0, max_units_per_step=1,
                     cost_shadow_price=0, risk_aversion=1, sync_penalty=1000)
        initial = State((0, 2, 2, 2), 6)
        policy = fixed_plan_policy((Allocation((1, 0, 0, 0)),) * 2)
        law = (1e-200, 0., 1.)
        # Independent binary-input oracle: losses after two, one, or zero
        # failures are 1004, 1, and 0. The missing p*p tail dominates utility,
        # despite its mass lying below the representable float range.
        with localcontext() as context:
            context.prec = 100
            p = Decimal.from_float(law[0])
            exact_utility = -(p * p * Decimal(1004).exp()
                              + 2 * p * Decimal(1).exp() + 1).ln()
        self.assertAlmostEqual(float(exact_utility), -82.96596280238173)
        regime = (((0, 0, 0, 0), law[0]), ((2, 2, 2, 2), law[2]))
        for audit in (lambda: evaluate(initial, cfg, policy, law),
                      lambda: evaluate_dependence(initial, cfg, policy, regime)):
            with self.subTest(audit=audit):
                with self.assertRaisesRegex(ValueError, "positive path probability underflow"):
                    audit()

    def test_mathematically_zero_paths_remain_impossible_not_errors(self):
        self.assertEqual(list(scenarios(2, (0., 0., 1.))), [((2, 2), 1.)])
        zero, full = (0, 0, 0, 0), (2, 2, 2, 2)
        self.assertEqual(list(dependent_scenarios(2, ((zero, 0.), (full, 1.)))),
                         [((full, full), 1.)])

    def test_representable_tiny_supported_paths_are_retained(self):
        self.assertEqual(list(scenarios(1, (5e-324, 0., 1.))),
                         [((0,), 5e-324), ((2,), 1.)])
        rare = 1e-150
        scalar = list(scenarios(2, (rare, 0., 1.)))
        self.assertEqual(scalar, [((0, 0), rare * rare), ((0, 2), rare),
                                  ((2, 0), rare), ((2, 2), 1.)])
        zero, full = (0, 0, 0, 0), (2, 2, 2, 2)
        self.assertEqual(list(dependent_scenarios(1, ((zero, 5e-324), (full, 1.)))),
                         [((zero,), 5e-324), ((full,), 1.)])
        dependent = list(dependent_scenarios(2, ((zero, rare), (full, 1.))))
        self.assertEqual(dependent, [((zero, zero), rare * rare),
                                     ((zero, full), rare), ((full, zero), rare),
                                     ((full, full), 1.)])


if __name__ == "__main__":
    unittest.main()
