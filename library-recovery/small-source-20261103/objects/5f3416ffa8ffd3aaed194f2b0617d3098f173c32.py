import math
import random
import unittest
from .hx_reproduced_slice import HX, original_pair, checked_pair
class Tests(unittest.TestCase):
    def test_frozen_reversal(self):
        p=HX(rate=.007595780582070804,
             payout=3.5072936797757205e-07,
             volatility=1.8581469732429565,
             maturity=2.2216211523554883e-08,
             shock_intensity=1.158839083935111e-13,
             sale_fraction=1.)
        v=1.000000000000002
        f,g=original_pair(p,v,p.maturity,1.0)
        self.assertEqual(f,0.9999999999942438)
        self.assertEqual(g,0.9999999999942439)
        with self.assertRaisesRegex(ArithmeticError,'ordering unresolved'):
            checked_pair(p,v,p.maturity,1.0)
    def test_regular_cases_preserve_values(self):
        p=HX()
        for ratio in (1.00001,1.1,2.,4.):
            for t in (1e-8,1.,p.maturity):
                a=checked_pair(p,ratio,t,1.)
                b=original_pair(p,ratio,t,1.)
                self.assertEqual(a,b)
    def test_seeded_accepted_equal_rejected_explicit(self):
        rng=random.Random(2026103107)
        accepted=rejected=0
        for _ in range(20000):
            p=HX(rate=10**rng.uniform(-5,-.5),payout=10**rng.uniform(-7,-.5),
                 volatility=10**rng.uniform(-2.8,.3),maturity=10**rng.uniform(-10,3),
                 shock_intensity=10**rng.uniform(-14,1),sale_fraction=1.)
            asset=math.exp(rng.uniform(math.log1p(4*math.ulp(1.)),4))
            try:
                old=original_pair(p,asset,p.maturity,1.)
            except (OverflowError,ValueError,ZeroDivisionError):
                rejected+=1
                continue
            try:
                new=checked_pair(p,asset,p.maturity,1.)
                self.assertEqual(new,old)
                accepted+=1
            except ArithmeticError:
                self.assertFalse(0<=old[1]<=old[0]<=1)
                rejected+=1
        print('slice scan: accepted',accepted,'refused',rejected)
        self.assertGreater(accepted,10000)
if __name__=='__main__':unittest.main()
