"""Scoped callback-equivalence and fail-closed transport tests, not admission."""
import math
import unittest
from unittest.mock import patch
from .hx import HX,_coupon_survival_annuity,bond_value
from . import coupon_compiled_research as c

class CompiledCouponTests(unittest.TestCase):
    def test_ordinary_and_discount_layer_parity(self):
        for p in (HX(),HX(rate=1e-20,sale_fraction=0.),HX(rate=1e8,payout=1e8,sale_fraction=0.)):
            for x in (.1,1.,50.):
                with self.subTest(p=p,x=x):
                    self.assertEqual(c.coupon_annuity_compiled(p,x,2.),_coupon_survival_annuity(p,x,2.))

    def test_each_sticky_failure_discards_quad_result(self):
        real=c._coupon_kernel.Context
        for code in (1,2,3):
            def factory(*args):
                ctx=real(*args);ctx.inject_failure(code);return ctx
            with self.subTest(code=code),patch.object(c._coupon_kernel,'Context',side_effect=factory):
                with self.assertRaisesRegex(ArithmeticError,'callback unresolved: '+str(code)):
                    c.coupon_annuity_compiled(HX(),.1,2.)
        # No global sticky contamination of the next independent call.
        self.assertEqual(c.coupon_annuity_compiled(HX(),.1,2.),_coupon_survival_annuity(HX(),.1,2.))

    def test_second_segment_failure_does_not_return_partial_sum(self):
        real=c._coupon_kernel.Context
        contexts=[]
        def factory(*args):
            ctx=real(*args);contexts.append(ctx);return ctx
        from scipy.integrate import quad
        calls=[]
        def failing_quad(fn,lo,hi,**kw):
            calls.append((lo,hi))
            if len(calls)==2:contexts[0].inject_failure(2)
            return quad(fn,lo,hi,**kw)
        with patch.object(c._coupon_kernel,'Context',side_effect=factory),patch('scipy.integrate.quad',side_effect=failing_quad):
            with self.assertRaisesRegex(ArithmeticError,'callback unresolved: 2'):
                c.coupon_annuity_compiled(HX(),.1,2.)
        self.assertEqual(len(calls),2)

    def test_actual_erased_survival_refuses(self):
        with self.assertRaises(ArithmeticError):
            c.coupon_annuity_compiled(HX(),math.ulp(0.),2.)

    def test_quad_warning_is_not_suppressed(self):
        from scipy.integrate import IntegrationWarning
        with patch('scipy.integrate.quad',side_effect=IntegrationWarning('injected failure')):
            with self.assertRaisesRegex(ArithmeticError,'integration unresolved'):
                c.coupon_annuity_compiled(HX(),.1,2.)

    def test_zero_coupon_and_actual_f_g_refusal(self):
        p=HX(coupon=0.)
        self.assertEqual(c.bond_value_compiled(p,80.,2.,64.),bond_value(p,80.,2.,64.,direct_coupon_survival=True))
        p=HX(rate=1.3090468849180657e-7,payout=.11176379671252477,volatility=.9066753141892397,maturity=.0002461050758857373,shock_intensity=.0009457207995848884,sale_fraction=1.)
        with self.assertRaisesRegex(ArithmeticError,'F/G first-passage'):
            c.bond_value_compiled(p,1.0000000000032205,p.maturity,1.)

    def test_full_output_message_and_unexpected_shapes_reject(self):
        for result in ((1.,0.,{},'nonconvergence'),(1.,0.,{},'failure',{}),(1.,0.)):
            with self.subTest(result=result),patch('scipy.integrate.quad',return_value=result):
                with self.assertRaisesRegex(ArithmeticError,'integration unresolved'):
                    c.coupon_annuity_compiled(HX(),.1,2.)

    def test_actual_quad_nonconvergence_matches_python_rejection(self):
        from scipy.integrate import quad
        def limited(*args,**kwargs):
            kwargs['limit']=1
            return quad(*args,**kwargs)
        with patch('scipy.integrate.quad',side_effect=limited):
            for helper in (_coupon_survival_annuity,c.coupon_annuity_compiled):
                with self.subTest(helper=helper.__name__):
                    with self.assertRaisesRegex(ArithmeticError,'integration unresolved'):
                        helper(HX(),.1,2.)

    def test_parallel_success_message_exception_and_sticky_priority(self):
        import threading
        import warnings
        from concurrent.futures import ThreadPoolExecutor
        from scipy.integrate import quad,IntegrationWarning
        local=threading.local()
        real=c._coupon_kernel.Context
        expected=_coupon_survival_annuity(HX(),.1,2.)
        original_filters=list(warnings.filters)
        def factory(*args):
            ctx=real(*args)
            if local.mode=='sticky':ctx.inject_failure(2)
            return ctx
        def controlled_quad(*args,**kwargs):
            self.assertEqual(kwargs.get('full_output'),1)
            if local.mode=='message':return (1.,0.,{},'injected nonconvergence')
            if local.mode=='exception':raise IntegrationWarning('injected warning exception')
            result=quad(*args,**kwargs)
            if local.mode=='sticky':return (*result,'simultaneous nonconvergence')
            return result
        def run(mode):
            local.mode=mode
            try:return mode,c.coupon_annuity_compiled(HX(),.1,2.)
            except ArithmeticError as exc:return mode,str(exc)
        modes=['success','message','exception','sticky']*16
        with patch.object(c._coupon_kernel,'Context',side_effect=factory),patch('scipy.integrate.quad',side_effect=controlled_quad):
            with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(run,modes))
        for mode,value in results:
            if mode=='success':self.assertEqual(value,expected)
            elif mode=='sticky':self.assertIn('callback unresolved: 2',value)
            else:self.assertIn('integration unresolved',value)
        self.assertEqual(warnings.filters,original_filters)
