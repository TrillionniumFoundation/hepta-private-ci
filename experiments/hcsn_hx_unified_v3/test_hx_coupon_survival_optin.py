"""Direct survival-coupon research regressions; no finite-domain certificate."""
import math
import unittest
from functools import partial
from unittest.mock import patch
from .hx import HX,bond_value as default_bond_value,_coupon_survival_annuity
from .hx import equity_resolvent
bond_value=partial(default_bond_value,direct_coupon_survival=True)

class CouponUnitDiscountTests(unittest.TestCase):
    def test_tiny_discount_tail_preserves_cashflows(self):
        p=HX(rate=1e-20,sale_fraction=0.)
        for tau in (.25,2.):
            expected=2*(-math.expm1(-p.q*tau)/p.q)+30*math.exp(-p.q*tau)
            self.assertAlmostEqual(bond_value(p,64*math.exp(50),tau,64),expected,delta=2e-12)

    def test_noninteger_cashflows_across_old_routing_seam(self):
        # Frozen independent #4422 density-duration oracle values, not
        # target F/G subtraction. Test both sides of the discarded threshold.
        expected={.1:22.174227530083243,1.:34.04770474681942,10.:34.184499999999886,50.:34.184499999999886}
        cut=16*math.ulp(1.)
        for x,reference in expected.items():
            for qt in (math.nextafter(cut,0.),cut,math.nextafter(cut,math.inf)):
                p=HX(rate=qt/2,sale_fraction=0.,coupon=4.123,principal=60.123)
                with self.subTest(x=x,qt=qt):
                    self.assertAlmostEqual(bond_value(p,64*math.exp(x),2.,64),reference,delta=2e-11)

    def test_zero_coupon_and_endpoints(self):
        p=HX(rate=1e-20,sale_fraction=0.,coupon=0.)
        self.assertEqual(bond_value(p,64*math.exp(50),2.,64),30.)
        self.assertEqual(bond_value(p,65.,0.,64),30.)
        self.assertEqual(bond_value(p,64.,2.,64),.6*64/2)

    def test_tiny_discount_does_not_need_division_by_q(self):
        # Direct time integral remains meaningful when q*t rounds to zero.
        p=HX(rate=math.ulp(0.),sale_fraction=0.)
        for tau in (.25,.75,1.5):
            with self.subTest(tau=tau):
                self.assertAlmostEqual(bond_value(p,64*math.exp(50),tau,64),30+2*tau,delta=2e-12)

    def test_existing_first_passage_refusal_is_not_bypassed(self):
        p=HX()
        # A formerly rejected ordinary subnormal tail now has a corrected
        # nonzero first term. Test guard non-bypass with an explicit refusal,
        # not by requiring the repaired arithmetic defect to remain broken.
        with patch('experiments.hcsn_hx_unified_v3.hx._first_passage_factors',
                   side_effect=ArithmeticError('HX F/G first-passage ordering unresolved in f64')):
            for pricing in (default_bond_value,bond_value):
                with self.assertRaisesRegex(ArithmeticError,'F/G first-passage'):
                    pricing(p,40306823.67318163,2.,64.62517667527493)

    def test_unresolved_survival_cancellation_refuses(self):
        p=HX()
        with self.assertRaisesRegex(ArithmeticError,'HX coupon survival'):
            _coupon_survival_annuity(p,math.ulp(0.),2.)

    def test_discount_boundary_layer_is_not_silently_missed(self):
        for q in (1e4,1e6,1e8):
            p=HX(rate=q,payout=q,sale_fraction=0.)
            annuity=_coupon_survival_annuity(p,50.,2.)
            self.assertAlmostEqual(annuity,1/q,delta=1e-12/q)

    def test_default_small_discount_refusal_is_unchanged(self):
        p=HX(rate=1e-20,sale_fraction=0.)
        with self.assertRaisesRegex(ArithmeticError,'stopped coupon unresolved'):
            default_bond_value(p,64*math.exp(.1),2.,64)
        self.assertGreater(bond_value(p,64*math.exp(.1),2.,64),0.)

    def test_equity_does_not_implicitly_opt_in(self):
        with patch('experiments.hcsn_hx_unified_v3.hx._coupon_survival_annuity',side_effect=AssertionError('unexpected opt-in')) as helper:
            try:
                equity_resolvent(HX(),100.,64.)
            except ArithmeticError:
                pass  # existing F/G refusal is independent of coupon opt-in
            helper.assert_not_called()
