"""Finite-maturity equity tail regression against independent outer integration."""

import math
import unittest

from .hx import HX, bond_value, boundary as financial_boundary, equity_resolvent
from ..hcsn_task_value_v1.gradient_audit import equity_quadrature_reference


class EquityFiniteMaturityTailTests(unittest.TestCase):
    def test_safe_finite_maturity_bond_is_not_perpetuity(self):
        for p in (HX(), HX(coupon=0.0), HX(coupon=20.0)):
            b = 1.0
            expected = (p.per_bond_coupon/p.q + math.exp(-p.q*p.maturity)
                        * (p.per_bond_principal-p.per_bond_coupon/p.q))
            actual = bond_value(p, math.exp(100), p.maturity, b)
            self.assertAlmostEqual(actual, expected, places=12)
            self.assertGreater(abs(actual-p.per_bond_coupon/p.q),
                               1000*math.ulp(max(1., abs(actual))))

    def test_resolved_negative_witness_against_full_outer_quadrature(self):
        p = HX(payout=0.0001, principal=1e20, coupon=0.0)
        asset = math.exp(30.0)
        reference = equity_quadrature_reference(p, asset, 1.0)
        value = equity_resolvent(p, asset, 1.0)
        allowance = (8*reference['quadrature_error_estimate_not_bound']
                     + 64*math.ulp(reference['value']))
        self.assertLess(abs(value-reference['value']), allowance)
        # Executed exact original blob b6afc3c9... before this repair.
        original_value = -1.2190455840023424e20
        self.assertGreater(abs(original_value-reference['value']), 100*allowance)

    def test_both_sign_principal_offsets_and_nominal_regimes(self):
        nominal_boundary = financial_boundary(HX())
        cases = ((HX(), 1.2, 1.0), (HX(), 3.0, 1.0),
                 (HX(), 1.6*nominal_boundary, nominal_boundary),
                 (HX(payout=.0001, principal=1e20, coupon=2e19),
                  math.exp(30), 1.0))
        for p, asset, boundary in cases:
            with self.subTest(coupon=p.coupon, asset=asset):
                reference = equity_quadrature_reference(p, asset, boundary)
                allowance = (8*reference['quadrature_error_estimate_not_bound']
                             + 128*math.ulp(reference['value']) + 2e-10)
                self.assertLess(abs(equity_resolvent(p, asset, boundary)
                                    - reference['value']), allowance)


if __name__ == '__main__':
    unittest.main()
