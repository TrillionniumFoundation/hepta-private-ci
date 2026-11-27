"""P0 true financial CPU FP32/BF16 forward/backward arithmetic, reject boundary."""
import math
import unittest
from .hx import HX,boundary
from .hx_financial_precision_screen import (
    screen_financial_bond,UnresolvedFinancialPrecision)

class HXFinancialPrecisionTests(unittest.TestCase):
    def test_real_cpu_dtype_and_gradient_vs_independent_bond_density(self):
        records=[]
        for p in (HX(),HX(sale_fraction=.2)):
            b=boundary(p)
            for ratio in (1.1,1.5,3):
                for dtype in ('fp32','bf16'):
                    with self.subTest(p=p,ratio=ratio,dtype=dtype):
                        x=screen_financial_bond(p,b*ratio,b,dtype)
                        records.append(x)
                        self.assertIn(x.status,('MEASURED_ONLY','REFUSE'))
                        if x.status=='MEASURED_ONLY':
                            self.assertTrue(math.isfinite(x.relative_error))
                            self.assertTrue(math.isfinite(x.normalized_gradient_error))
                            if dtype=='fp32':
                                self.assertLess(x.relative_error,2e-4)
                                self.assertLess(x.normalized_gradient_error,2e-3)
        self.assertGreaterEqual(sum(x.status=='MEASURED_ONLY' for x in records),6)

    def test_near_default_refuses_even_when_values_quantize_equal(self):
        p=HX();b=boundary(p)
        for dtype in ('fp32','bf16'):
            for eps in (1e-7,1e-5):
                self.assertEqual(screen_financial_bond(p,b*(1+eps),b,dtype).status,
                                 'REFUSE')

    def test_invalid_and_unsupported_input_refusals(self):
        p=HX();b=boundary(p)
        for asset in (0.,b,b-1,float('inf')):
            with self.assertRaises(UnresolvedFinancialPrecision):
                screen_financial_bond(p,asset,b,'fp32')
        with self.assertRaises(UnresolvedFinancialPrecision):
            screen_financial_bond(p,b*2,b,'fp16')

if __name__=='__main__':
    unittest.main()
