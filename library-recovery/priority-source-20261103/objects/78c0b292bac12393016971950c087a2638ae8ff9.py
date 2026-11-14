"""Independent high-precision cross-checks and negative admission cases.

mpmath is used ONLY for an independent test oracle; the interval source under
review is rationals + proved analytical truncation bounds, not mpmath.
"""
import unittest
from fractions import Fraction
from mpmath import mp
from rational_fpt_certificate import (
    certified_fpt, decimal, cdf_point, pi, exp_point, sqrt_point,
)
from qvi_rational_certificate import known_case, certify, solve_exact
from fpt_reference import _formula
from qvi_toy import audit as float_qvi_audit


def mp_fraction(q:Fraction):
    return mp.mpf(q.numerator)/q.denominator


def interval_includes(d, value):
    return mp.mpf(d['lower'])<=value<=mp.mpf(d['upper'])


class CertifiedScalarBounds(unittest.TestCase):
    def test_pi_enclosure_independent_high_precision(self):
        with mp.workdps(120):
            b=pi(65)
            self.assertLess(mp_fraction(b.lo),mp.pi)
            self.assertGreater(mp_fraction(b.hi),mp.pi)
            self.assertLess(mp_fraction(b.hi-b.lo),mp.mpf('1e-67'))

    def test_cdf_and_exp_bounds(self):
        for z in ('0','.2','1','-1','4','-4'):
            with self.subTest(z=z),mp.workdps(120):
                b=cdf_point(decimal(z),65)
                ref=mp.erfc(-mp.mpf(z)/mp.sqrt(2))/2
                self.assertLessEqual(mp_fraction(b.lo),ref)
                self.assertGreaterEqual(mp_fraction(b.hi),ref)
        for y in ('0','.0001','-0.005','.5','-2.5','5'):
            with self.subTest(y=y),mp.workdps(120):
                b=exp_point(decimal(y),65)
                self.assertLessEqual(mp_fraction(b.lo),mp.exp(mp.mpf(y)))
                self.assertGreaterEqual(mp_fraction(b.hi),mp.exp(mp.mpf(y)))

    def test_sqrt_bound(self):
        for x in ('0','2','3','1.02'):
            with self.subTest(x=x),mp.workdps(120):
                b=sqrt_point(decimal(x),70)
                self.assertLessEqual(mp_fraction(b.lo),mp.sqrt(mp.mpf(x)))
                self.assertGreaterEqual(mp_fraction(b.hi),mp.sqrt(mp.mpf(x)))

    def test_certificates_against_independent_fpt_closed_form(self):
        cases=[
          ('0.8','-0.3','0.7','0.9','0.05'),
          ('1.2','0.1','0.6','1.1','0.4'),
          ('0.1','0.4','1.3','0.5','0.3'),
          ('2.0','-0.2','1.0','2.0','0.1'),
          ('0.001','-0.03','1.2','0.5','0.3'),
          ('0.8','-0.3','0.7','0.9','1e-22'),
        ]
        for case in cases:
            with self.subTest(case=case):
                report=certified_fpt(*case,places=65)
                self.assertEqual(report['decision'],'CERTIFIED_POSITIVE_F_MINUS_G')
                with mp.workdps(120):
                    F,G=_formula(*map(mp.mpf,case))
                    self.assertTrue(interval_includes(report['F'],F))
                    self.assertTrue(interval_includes(report['G'],G))
                    self.assertTrue(interval_includes(report['F_minus_G'],F-G))
                    self.assertLess(mp.mpf(report['F_minus_G']['lower']),F-G)
                    self.assertGreater(mp.mpf(report['F_minus_G']['lower']),0)

    def test_strict_rejection_of_unqualified_domains(self):
        bad=[('0','-.3','.7','.9','.05'),('.8','-.3','.7','.9','0'),
             ('.8','-.3','0','.9','.05'),('.8','-.3','.7','0','.05'),
             ('.8','-.3','.001','.9','.05'),('NaN','-.3','.7','.9','.05'),
             ('.8','-.3','.7','1e400','.05')]
        for args in bad:
            with self.subTest(args=args),self.assertRaises((ValueError,ArithmeticError)):
                certified_fpt(*args)
        with self.assertRaises(ValueError):
            certified_fpt(.8,'-.3','.7','.9','.05')
        with self.assertRaises(ArithmeticError):
            certified_fpt('0.8','-4','0.02','0.9','0.05')


class ExactRegenerationQVI(unittest.TestCase):
    def test_closed_exact_bellman_and_float_reference(self):
        r=known_case()
        self.assertEqual(r['enumerated_policies'],16)
        self.assertEqual(r['bellman_residual_exact'],'0')
        self.assertEqual(r['optimal_reset_actions'],[False,False,False,True])
        self.assertFalse(r['full_HX_qvi_certified'])
        f=float_qvi_audit()
        for v,w in zip(r['exact_values'],f['values']):
            self.assertAlmostEqual(float(Fraction(v)),w,delta=2e-11)

    def test_negative_matrix_and_discount(self):
        with self.assertRaises(ValueError):
            certify([['.9','.2'],['0','1']],['0','1'],['0','1'],'.9')
        with self.assertRaises(ValueError):
            certify([['1','0'],['0','1']],['0','1'],['0','1'],'1')
        with self.assertRaises(ValueError):
            certify([['1','0'],['-.1','1.1']],['0','1'],['0','1'],'.9')

    def test_exact_solver_correctness(self):
        v=solve_exact([[Fraction(2),Fraction(1)],
                       [Fraction(1),Fraction(3)]],
                      [Fraction(7),Fraction(9)])
        self.assertEqual(v,[Fraction(12,5),Fraction(11,5)])


if __name__=='__main__':unittest.main()

class CertifiedBoundaryGradient(unittest.TestCase):
    def test_zero_boundary_right_derivative_is_nonzero(self):
        from rational_fpt_certificate import certified_risk_distance_gradient
        for mu,sigma,t in [('-0.3','0.7','0.9'),('0','0.6','1'),('0.4','1.1','0.75')]:
            r=certified_risk_distance_gradient('0',mu,sigma,t,places=65)
            self.assertTrue(r['strictly_negative_certified'])
            self.assertFalse(r['boundary_smooth_pasting_certified'])
            with mp.workdps(110):
                x=mp.zero;m=mp.mpf(mu);s=mp.mpf(sigma);T=mp.mpf(t)
                scale=s*mp.sqrt(T)
                z1=(-x-m*T)/scale;z2=(-x+m*T)/scale
                pdf=lambda z:mp.exp(-z*z/2)/mp.sqrt(2*mp.pi)
                phi=lambda z:mp.erfc(-z/mp.sqrt(2))/2
                expected=-pdf(z1)/scale +(-2*m/s**2*phi(z2)-pdf(z2)/scale)
                self.assertTrue(interval_includes(r['gradient'],expected))

    def test_interior_gradient_is_negative(self):
        from rational_fpt_certificate import certified_risk_distance_gradient
        for x in ('.01','.2','.8','2.5'):
            r=certified_risk_distance_gradient(x,'-.3','.7','.9',places=65)
            self.assertTrue(r['strictly_negative_certified'])

class IndependentQuadratureCrossCheck(unittest.TestCase):
    def test_quadrature_independent_integral_representation(self):
        from fpt_reference import FPT, transformed_integral
        cases=[('0.8','-0.3','0.7','0.9','0.05'),
               ('0.1','0.4','1.3','0.5','0.3'),
               ('1.2','0.1','0.6','1.1','0.4')]
        for args in cases:
            with self.subTest(args=args):
                certified=certified_fpt(*args,places=60)
                numerical=transformed_integral(FPT(*map(float,args)),dps=75)
                # This is a cross-check, not a validated quadrature bound:
                # comparison must be tolerant of quadrature truncation.
                with mp.workdps(80):
                    for k in ('F','G'):
                        lo=mp.mpf(certified[k]['lower']);hi=mp.mpf(certified[k]['upper'])
                        ref=mp.mpf(numerical[k])
                        self.assertLess(abs(ref-(lo+hi)/2),mp.mpf('1e-50'))

    def test_reject_huge_decimal_exponent_without_allocating(self):
        with self.assertRaises(ValueError):
            certified_fpt('1e999999999999999999999','-.3','.7','.9','.05')
