"""Exact-sign adversarial tests, with independent Fraction construction."""
from fractions import Fraction
import unittest

from .hx_exact_curvature_gate import check_hx_local_curvature


class ExactHXCurvatureTests(unittest.TestCase):
    @staticmethod
    def valid(**overrides):
        p = dict(boundary='100', dividend_yield='0.2', rollover_fraction='0.5',
                 coupon='2', recovery_fraction='0.5', maturity='5',
                 principal='100', sigma='0.2')
        p.update(overrides)
        return p

    def test_negative_curvature_implies_reject(self):
        r = check_hx_local_curvature(**self.valid())
        self.assertEqual(r.decision, 'REJECT_NEGATIVE_LOCAL_CONTINUATION')
        self.assertEqual(Fraction(r.boundary_cashflow_numerator,
                                  r.boundary_cashflow_denominator), Fraction(9))
        self.assertEqual(r.curvature_sign, -1)
        self.assertFalse(r.global_obstacle_certified)

    def test_local_positive_curvature_does_not_admit(self):
        r = check_hx_local_curvature(**self.valid(dividend_yield='0.02'))
        self.assertEqual(r.decision, 'LOCAL_NECESSARY_ONLY_GLOBAL_UNCERTIFIED')
        self.assertEqual(r.curvature_sign, 1)
        self.assertFalse(r.global_obstacle_certified)

    def test_exact_zero_remains_unresolved(self):
        r = check_hx_local_curvature(**self.valid(dividend_yield='0.11'))
        self.assertEqual(r.decision, 'UNRESOLVED_ZERO_CURVATURE')
        self.assertEqual((r.boundary_cashflow_numerator,r.curvature_sign), (0,0))

    def test_tiny_decimal_sign(self):
        r = check_hx_local_curvature(**self.valid(dividend_yield='0.110000000000000000000000001'))
        self.assertEqual(r.decision, 'REJECT_NEGATIVE_LOCAL_CONTINUATION')
        self.assertGreater(r.boundary_cashflow_numerator, 0)

    def test_multiscale_cancellation_witness(self):
        # m*delta*b -m*(1-pi)*coupon = 10**100, alpha*b=10**-100,
        # principal=10**100; exact f=10**-200. A 120-digit Decimal
        # accumulator can round the tiny contribution away before cancellation.
        r = check_hx_local_curvature(boundary='1', dividend_yield='1e100',
            rollover_fraction='1e-100', coupon='1e100',
            recovery_fraction='1e-100', maturity='1e100',
            principal='1e100', sigma='0.2')
        self.assertEqual(r.decision, 'REJECT_NEGATIVE_LOCAL_CONTINUATION')
        self.assertEqual(Fraction(r.boundary_cashflow_numerator,
                                  r.boundary_cashflow_denominator), Fraction(1, 10**200))
        self.assertEqual(r.curvature_sign, -1)

    def test_sign_and_curvature_under_positive_scale(self):
        base = self.valid(dividend_yield='0.02')
        a = check_hx_local_curvature(**base)
        scaled = dict(base)
        for name in ('boundary', 'coupon', 'principal'):
            scaled[name] = str(int(base[name])*1000)
        b = check_hx_local_curvature(**scaled)
        self.assertEqual(a.decision, b.decision)
        self.assertEqual(Fraction(b.boundary_cashflow_numerator,
                                  b.boundary_cashflow_denominator),
                         1000*Fraction(a.boundary_cashflow_numerator,
                                       a.boundary_cashflow_denominator))

    def test_invalid_parameters_and_ambiguous_float_refused(self):
        for field, value in [('boundary', '0'), ('sigma','0'),
                             ('maturity','0'), ('rollover_fraction','1.00001'),
                             ('recovery_fraction','-0.01'), ('coupon',True),
                             ('principal','NaN'), ('dividend_yield', float('inf')),
                             ('coupon', 0.1), ('dividend_yield','1e101'),
                             ('coupon','1.1234567890123456789012345678901')]:
            with self.subTest(field=field, value=value):
                with self.assertRaises(ValueError):
                    check_hx_local_curvature(**self.valid(**{field:value}))


if __name__ == '__main__':
    unittest.main()
