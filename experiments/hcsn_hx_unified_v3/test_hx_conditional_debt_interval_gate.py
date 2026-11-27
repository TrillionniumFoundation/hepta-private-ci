"""Standalone stdlib tests of conditional quantized HX perturbation bounds."""
from dataclasses import replace
from types import SimpleNamespace
import math
import unittest
from fractions import Fraction

from .hx_conditional_debt_interval_gate import (conditional_debt_error_gate,
                                                 UnresolvedDebtInterval)


def _synthetic_grid(*, debt=0.0, high=0.0, value=0.0, n=33):
    return SimpleNamespace(nodes=n, candidate_barrier=1.0, log_upper=0.5,
                           debt_values=tuple(float(debt) for _ in range(n)),
                           equity_values=tuple([0.0]+[float(value)]*(n-2)+[float(high)]))


def _p(*, payout=.01, principal=1.0):
    return SimpleNamespace(rate=.5,payout=payout,volatility=.2,
                           maturity=1.0,principal=principal,
                           coupon=0.0,tax_shield=0.0)


class ConditionalDebtGateTests(unittest.TestCase):
    def test_zero_error_exact_stop_classification(self):
        # Every cashflow is strictly negative and the zero obstacle is exact.
        result=conditional_debt_error_gate(_p(),_synthetic_grid(),
                    debt_error='0',upper_equity_error='0')
        self.assertEqual(len(result.guaranteed_stop),31)
        self.assertFalse(result.ambiguous)
        self.assertEqual(result.exact_nominal_residual,0)
        self.assertEqual(result.sup_value_perturbation,0)
        self.assertFalse(result.scientific_gate_closed)
        self.assertFalse(result.input_error_bounds_verified)
        self.assertFalse(result.production_activation)

    def test_debt_error_can_invalidate_all_stops(self):
        g=_synthetic_grid()
        small=conditional_debt_error_gate(_p(),g,debt_error='0',upper_equity_error='0')
        large=conditional_debt_error_gate(_p(),g,debt_error='2',upper_equity_error='0')
        self.assertEqual(len(small.guaranteed_stop),31)
        self.assertFalse(large.guaranteed_stop)
        self.assertEqual(len(large.ambiguous),31)

    def test_upper_boundary_uncertainty_must_propagate(self):
        g=_synthetic_grid()
        base=conditional_debt_error_gate(_p(),g,debt_error='0',upper_equity_error='0')
        uncertain=conditional_debt_error_gate(_p(),g,debt_error='0',upper_equity_error='10')
        self.assertLess(base.sup_value_perturbation,uncertain.sup_value_perturbation)
        self.assertLess(len(uncertain.guaranteed_stop),len(base.guaranteed_stop))
        self.assertFalse(uncertain.guaranteed_continue)

    def test_rounded_binary64_input_is_rational_not_decimal_ideal(self):
        g=_synthetic_grid()
        s=conditional_debt_error_gate(_p(),g,debt_error='0.1',upper_equity_error='0.01')
        self.assertEqual(s.cashflow_abs_budget,Fraction(1,10))
        self.assertEqual(s.upper_equity_abs_budget,Fraction(1,100))
        self.assertLess(s.contraction,1)
        self.assertGreater(s.continuation_error_budget,0)

    def test_nominal_nonzero_residual_enlarges_error(self):
        g=_synthetic_grid(value=0.02)
        c=conditional_debt_error_gate(_p(),g,debt_error='0',upper_equity_error='0')
        self.assertGreater(c.exact_nominal_residual,0)
        self.assertGreater(c.sup_value_perturbation,0)

    def test_robust_continue_possible_on_positive_cashflow(self):
        p=_p(payout=2.0,principal=.5)
        # Construct the finite-grid Bellman fixed point via monotone iteration.
        g=_synthetic_grid()
        n=g.nodes; h=g.log_upper/(n-1)
        drift=p.rate-p.payout-.5*p.volatility**2
        diff=.5*(p.volatility/h)**2
        ql=diff-drift/(2*h);qr=diff+drift/(2*h)
        if min(ql,qr)<0:
            ql=diff+max(0.,-drift)/h
            qr=diff+max(0.,drift)/h
        den=p.rate+ql+qr
        v=[0.]*n
        for _ in range(2500):
            next_v=v.copy()
            for i in range(1,n-1):
                f=p.payout*math.exp(i*h)-p.principal
                next_v[i]=max(0.,(ql*v[i-1]+qr*v[i+1]+f)/den)
            v=next_v
        grid=_synthetic_grid()
        grid.equity_values=tuple(v)
        c=conditional_debt_error_gate(p,grid,debt_error='0',upper_equity_error='0')
        self.assertGreater(len(c.guaranteed_continue),0)
        self.assertFalse(c.guaranteed_stop)
        self.assertFalse(c.ambiguous)

    def test_invalid_decimal_budget_rejected(self):
        for err in ('-1','NaN','Infinity','1e999','untrusted','0.0;DROP',''):
            with self.subTest(err=err),self.assertRaises(UnresolvedDebtInterval):
                conditional_debt_error_gate(_p(),_synthetic_grid(),debt_error=err,upper_equity_error='0')
        for err in (0.1,None,True):
            with self.subTest(err=err),self.assertRaises(UnresolvedDebtInterval):
                conditional_debt_error_gate(_p(),_synthetic_grid(),debt_error=err,upper_equity_error='0')

    def test_invalid_domain_and_nonfinite_values_rejected(self):
        broken=_synthetic_grid()
        broken.equity_values=(1.0,)+broken.equity_values[1:]
        cases=[(_p(),broken),(_p(),_synthetic_grid(n=17)),
               (_p(),_synthetic_grid(value=float('nan'))),
               (_p(),_synthetic_grid(high=float('inf'))),
               (_p(),_synthetic_grid(debt=float('nan'))),
               (_p(payout=-1),_synthetic_grid()),
               (_p(),_synthetic_grid(n=1041))]
        for p,g in cases:
            with self.subTest(n=g.nodes,p=p),self.assertRaises(UnresolvedDebtInterval):
                conditional_debt_error_gate(p,g,debt_error='0',upper_equity_error='0')

    def test_boundary_budget_not_zeroed_when_no_debt_error(self):
        c=conditional_debt_error_gate(_p(),_synthetic_grid(),debt_error='0',upper_equity_error='1e-5')
        self.assertGreaterEqual(c.sup_value_perturbation,Fraction(1,100000))
        self.assertGreater(c.continuation_error_budget,0)

if __name__=='__main__':
    unittest.main()
