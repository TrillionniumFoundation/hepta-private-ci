"""Reject unresolved binary64 one-shot cost translations; research-only P0 gate.

Independent Decimal displacement audit is based on the represented input floats.
The f64 ULP policy is a necessary engineering guard, not interval certification
or a He--Xiong coupled finance QVI proof.
"""
from decimal import Decimal, localcontext
import math
import random
import unittest

from .stopping import Stop, one_shot_boundary, one_shot_value


class OneShotCostULPGateTests(unittest.TestCase):
    def test_positive_large_cost_rejects_false_precision(self):
        for cost in (1e9, 1e10, 1e12, 1e14):
            p = Stop(0., 1., .007, cost, cost - 10., 0.)
            with self.subTest(cost=cost), self.assertRaisesRegex(
                ArithmeticError, 'One-shot boundary resolution'
            ):
                one_shot_boundary(p)
            with self.subTest(value_cost=cost), self.assertRaises(ArithmeticError):
                one_shot_value(p, cost)

    def test_negative_large_cost_rejects_false_precision(self):
        for cost in (-1e9, -1e10, -1e12):
            p = Stop(0., 1., .007, cost, cost - 10., 0.)
            with self.subTest(cost=cost), self.assertRaisesRegex(
                ArithmeticError, 'One-shot boundary resolution'
            ):
                one_shot_boundary(p)

    def test_resolved_offsets_match_independent_decimal(self):
        for cost in (0., 1e4, 1e6, 1e8, -1e8):
            p = Stop(0., 1., .007, cost, cost - 10., 0.)
            b = one_shot_boundary(p)
            with localcontext() as ctx:
                ctx.prec = 90
                ideal = Decimal.from_float(cost) + 1 / Decimal.from_float(p.kappa)
                expected = float(ideal - Decimal.from_float(cost))
            self.assertLessEqual(abs((b - cost) - expected), 2 * math.ulp(b))
            self.assertLessEqual(math.ulp(b), 1e-8 / p.kappa)

    def test_nonfinite_immediate_reward_still_rejected_on_admissible_boundary(self):
        # The prior test used a severely quantized boundary; this input
        # preserves a well-resolved boundary but still overflows x-cost.
        p = Stop(5e306, 1., .1, -1e308, -1.2e308, 0.)
        self.assertLess(math.ulp(one_shot_boundary(p)), 1e-8 / p.kappa)
        with self.assertRaisesRegex(ArithmeticError, 'One-shot value'):
            one_shot_value(p, 1e308)

    def test_seeded_cost_translation_error_or_explicit_refusal(self):
        rng = random.Random(2026103131)
        admitted = refused = 0
        for _ in range(256):
            cost = rng.choice((-1., 1.)) * 10 ** rng.uniform(-3., 14.)
            rho = 10 ** rng.uniform(-3., .5)
            p = Stop(0., 1., rho, cost,
                     cost - max(10., 4 * math.ulp(cost)), 0.)
            displacement = 1 / p.kappa
            try:
                b = one_shot_boundary(p)
            except ArithmeticError:
                refused += 1
                continue
            admitted += 1
            self.assertLessEqual(math.ulp(b), 1e-8 * displacement)
            with localcontext() as ctx:
                ctx.prec = 90
                ideal = Decimal.from_float(cost) + 1 / Decimal.from_float(p.kappa)
                expected = float(ideal - Decimal.from_float(cost))
            self.assertLessEqual(abs((b - cost) - expected), 2 * math.ulp(b))
        self.assertGreater(admitted, 0)
        self.assertGreater(refused, 0)


if __name__ == '__main__':
    unittest.main()
