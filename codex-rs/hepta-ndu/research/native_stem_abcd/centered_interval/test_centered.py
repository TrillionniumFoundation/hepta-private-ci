"""R22 mathematical/derivative tests independent of fitted-model efficacy."""
import unittest
from fractions import Fraction as F
from tempfile import TemporaryDirectory
from pathlib import Path
import numpy as np
import mpmath as mp
from centered import (D,old,outward,interval_abs,dq_bounds,tanh_interval,
                      tanh_point_bounds,_tanh_cf_positive,gradient_bounds,
                      centered_lower,hybrid_lower,cert,LAMBERT_DEPTH)

mp.mp.dps=75

def independently_mpmath(theta):
    n=len(theta); a,b=theta[:2]
    c=theta[2] if n>=3 else mp.mpf(0)
    d=theta[3] if n>=4 else mp.mpf(0)
    v=a-b
    q=lambda z,k:k*z/(1+z*z)
    shared=v*v/4+q(a,mp.mpf(1)/25)+q(v,mp.mpf(1)/8)
    gamma=mp.mpf(9)/10
    ans=mp.mpf(0)
    def ce(x,y,rho):
        return (mp.log(mp.exp(rho*x)+mp.exp(rho*y))-mp.log(2))/rho
    for x in (-1,1):
      h1=a*x+c
      h2=b*h1+d*h1*h1/4+shared
      for p0 in (0,1):
        outer=[]
        for e1 in (-1,1):
          p1=p0^(e1==1)
          leaves=[]
          for e2 in (-1,1):
            p2=p1^(e2==1)
            r=h2+mp.mpf(e2)/10-x-1
            leaves.append(r*r+mp.mpf(p2)/50)
          outer.append(mp.mpf(p1)/20+gamma*ce(*leaves,mp.mpf(1)/2 if p1==0 else mp.mpf(1)))
        ans+=gamma*ce(*outer,mp.mpf(1)/2 if p0==0 else mp.mpf(1))/4
    return ans+sum(t*t/4 for t in theta)

class CenteredTests(unittest.TestCase):
    def test_01_outward_floor_ceil(self):
        x=F(-4,7);y=F(1234567,7654321)
        lo,hi=outward((x,y),10**9)
        self.assertTrue(lo<=x<=hi and lo<=y<=hi)
        self.assertEqual(outward((F(1,2),F(1,2))),(F(1,2),F(1,2)))
    def test_02_derivative_q_extrema(self):
        for k in (F(1,25),F(1,8)):
            for lo,hi in [(F(-5),F(5)),(F(0),F(1,2)),(F(-3),F(-1)),(F(2),F(5))]:
                x=dq_bounds((lo,hi),k)
                for t in np.linspace(float(lo),float(hi),21):
                    z=F(str(t));dv=k*(1-z*z)/(1+z*z)**2
                    self.assertLessEqual(x[0],dv);self.assertGreaterEqual(x[1],dv)
    def test_03_continued_fraction_tail_brackets(self):
        for z in (F(0),F(1,10),F(1,2),F(1),F(2),F(3),F(4)):
            lb,ub=tanh_point_bounds(z)
            true=mp.tanh(mp.mpf(z.numerator)/z.denominator)
            self.assertLessEqual(mp.mpf(lb.numerator)/lb.denominator,true)
            self.assertGreaterEqual(mp.mpf(ub.numerator)/ub.denominator,true)
            if z<=2:self.assertLess(float(ub-lb),2e-5)
    def test_04_interval_tanh_signed_and_extreme(self):
        for lo,hi in [(F(-4),F(4)),(F(-3),F(0)),(F(-1,2),F(2,3)),(F(1,4),F(9,10)),(F(8),F(10))]:
            a,b=tanh_interval((lo,hi))
            for z in np.linspace(float(lo),float(hi),15):
                true=mp.tanh(mp.mpf(str(z)))
                self.assertLessEqual(mp.mpf(a.numerator)/a.denominator,true)
                self.assertGreaterEqual(mp.mpf(b.numerator)/b.denominator,true)
    def test_05_hybrid_never_weaker(self):
        for n in (2,3,4):
            for rad in (F(1),F(1,4),F(1,16)):
                box=tuple((F(s)-rad,F(s)+rad) for s in old.CANDIDATES[n])
                self.assertGreaterEqual(hybrid_lower(box),old.cost_bounds(box)[0])
    def test_06_independent_mpmath_derivative_box_2(self):self._derivatives(2)
    def test_07_independent_mpmath_derivative_box_3(self):self._derivatives(3)
    def test_08_independent_mpmath_derivative_box_4(self):self._derivatives(4)
    def _derivatives(self,n):
        mids=[F(s) for s in old.CANDIDATES[n]]
        # Fixed positive and negative perturbations, including some away from optimum
        for shift in (F(0),F(1,4),F(-1,3)):
            theta=[v+shift for v in mids]
            box=tuple((x-F(1,50),x+F(1,50)) for x in theta)
            bnds=gradient_bounds(box)
            args=[mp.mpf(x.numerator)/x.denominator for x in theta]
            for k in range(n):
                der=mp.diff(lambda t: independently_mpmath(args[:k]+[t]+args[k+1:]),args[k])
                lo,hi=bnds[k]
                self.assertLessEqual(mp.mpf(lo.numerator)/lo.denominator,der)
                self.assertGreaterEqual(mp.mpf(hi.numerator)/hi.denominator,der)
            actual=independently_mpmath(args)
            b=hybrid_lower(box)
            self.assertLessEqual(mp.mpf(b.numerator)/b.denominator,actual)
    def test_09_interval_point_matches_legacy(self):
        for n in (2,3,4):
            p=tuple((F(s),F(s)) for s in old.CANDIDATES[n])
            self.assertEqual(hybrid_lower(p),old.cost_bounds(p)[0])
    def test_10_after_cap_no_false_certification(self):
        with TemporaryDirectory() as tmp:
            c=cert(4,Path(tmp)/'proof',node_cap=7)
            self.assertEqual(c['splits'],7)
            self.assertFalse(c['qualifies'])
            self.assertGreater(F(c['global_regret_upper']),F(1,100))
    def test_11_all_math_is_fraction(self):
        box=tuple((-F(1,5),F(3,10)) for _ in range(4))
        self.assertIsInstance(centered_lower(box),F)
        for x in gradient_bounds(box):
            self.assertTrue(all(isinstance(z,F) for z in x))
    def test_12_closed_interval_input_validation(self):
        with self.assertRaises(ValueError):gradient_bounds(((F(1),F(0)),(F(0),F(1))))
        with self.assertRaises(ValueError):tanh_interval((F(1),F(0)))
        with self.assertRaises(ValueError):cert(6,'/tmp/invalid-r22-box')
if __name__=='__main__':unittest.main(verbosity=2)
