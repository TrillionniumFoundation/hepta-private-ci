import unittest
from decimal import Decimal
from .hx_curvature_necessary import hx_local_curvature_gate


class HXCurvatureTests(unittest.TestCase):
    @staticmethod
    def sample(dividend='0.2'):
        return dict(boundary='100',dividend_yield=dividend,
                    rollover_fraction='0.5',coupon='2',
                    recovery_fraction='0.5',maturity='5',
                    principal='100',sigma='0.2')

    def test_positive_boundary_cashflow_rejects(self):
        r=hx_local_curvature_gate(**self.sample())
        self.assertEqual(r.status,'REJECT_NEGATIVE_LOCAL_CONTINUATION')
        self.assertEqual(Decimal(r.boundary_cashflow),Decimal('9'))
        self.assertLess(Decimal(r.boundary_second_derivative),0)
        self.assertFalse(r.global_obstacle_certified)

    def test_negative_boundary_cashflow_only_necessary(self):
        r=hx_local_curvature_gate(**self.sample('0.02'))
        self.assertEqual(r.status,'LOCAL_NECESSARY_ONLY_GLOBAL_UNCERTIFIED')
        self.assertGreater(Decimal(r.boundary_second_derivative),0)
        self.assertFalse(r.global_obstacle_certified)

    def test_exact_zero_does_not_pass(self):
        r=hx_local_curvature_gate(**self.sample('0.11'))
        self.assertEqual(r.status,'UNRESOLVED_ZERO_CURVATURE')

    def test_below_binary64_decimal_sign_retained(self):
        r=hx_local_curvature_gate(**self.sample('0.110000000000000000000000001'))
        self.assertEqual(r.status,'REJECT_NEGATIVE_LOCAL_CONTINUATION')
        self.assertGreater(Decimal(r.boundary_cashflow),0)

    def test_invalid_and_float_inputs_fail_closed(self):
        for key,value in (('sigma','0'),('rollover_fraction','1.01'),
                          ('dividend_yield','-0.1'),('maturity','0'),
                          ('boundary','Infinity'),('recovery_fraction',0.3),
                          ('coupon',True),('principal','NaN')):
            args=self.sample();args[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):
                hx_local_curvature_gate(**args)

    def test_scale_homogeneity_curvature(self):
        r=hx_local_curvature_gate(**self.sample('0.02'))
        new=self.sample('0.02')
        for f in ('boundary','coupon','principal'):
            new[f]=str(Decimal(new[f])*Decimal('1000'))
        rr=hx_local_curvature_gate(**new)
        self.assertEqual(Decimal(rr.boundary_cashflow),
                         Decimal(r.boundary_cashflow)*Decimal('1000'))
        self.assertEqual(Decimal(rr.boundary_second_derivative),
                         Decimal(r.boundary_second_derivative)/Decimal('1000'))


if __name__=='__main__':
    unittest.main()
