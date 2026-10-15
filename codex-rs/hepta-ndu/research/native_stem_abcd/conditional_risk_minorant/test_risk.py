"""R23 independent scalar-risk/global quadratic minorant verification."""
import unittest
import sys
from fractions import Fraction as F
import numpy as np
import mpmath as mp
from risk_minorant import (old,centered,G,phi_anchor,residual_range,precompute_anchors,
                           scalar_minorant,quadratic_tangent_min,score,cert)
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'centered_interval'))
from test_centered import independently_mpmath
mp.mp.dps=75


def mp_f(f):
    return mp.mpf(f.numerator)/f.denominator


def phi_mp(r):
    gam=mp.mpf(9)/10
    ce=lambda u,v,rho:mp.log((mp.exp(rho*u)+mp.exp(rho*v))/2)/rho
    out=mp.mpf(0)
    for p0 in (0,1):
        stage=[]
        for e1 in (-1,1):
            p1=p0^(e1==1)
            leaves=[]
            for e2 in (-1,1):
                p2=p1^(e2==1)
                leaves.append((r+mp.mpf(e2)/10)**2+mp.mpf(p2)/50)
            stage.append(mp.mpf(p1)/20+gam*ce(*leaves,mp.mpf(1)/2 if p1==0 else mp.mpf(1)))
        out+=gam*ce(*stage,mp.mpf(1)/2 if p0==0 else mp.mpf(1))/4
    return out


class Tests(unittest.TestCase):
    def test_01_risk_decomposition_independent(self):
        for n in (2,3,4):
            theta=[F(s) for s in old.CANDIDATES[n]]
            pt=tuple((x,x) for x in theta)
            r=[mp_f(residual_range(pt,x)[0]) for x in (-1,1)]
            value=sum(phi_mp(x) for x in r)+sum(mp_f(x)**2 for x in theta)/4
            val2=independently_mpmath([mp_f(x) for x in theta])
            self.assertLess(abs(value-val2),mp.mpf('1e-68'))

    def test_02_exact_anchor_bounds_and_derivatives(self):
        for n in (2,3,4):
            for x,(r,low,high,deriv) in precompute_anchors(n).items():
                phi=phi_mp(mp_f(r))
                g=mp.diff(phi_mp,mp_f(r))
                self.assertLessEqual(mp_f(low),phi)
                self.assertGreaterEqual(mp_f(high),phi)
                self.assertLessEqual(mp_f(deriv[0]),g)
                self.assertGreaterEqual(mp_f(deriv[1]),g)

    def test_03_strong_convex_phi(self):
        for r in (-3,-1,-.2,0,.4,1,3):
            der2=mp.diff(phi_mp,mp.mpf(r),2)
            self.assertGreaterEqual(der2,mp.mpf(81)/100-mp.mpf('1e-50'))

    def test_04_joint_quadratic_min_signed_segments(self):
        intervals=[(F(-2),F(2)),(F(-2),F(-1)),(F(1),F(2)),(F(0),F(1,2))]
        for d in intervals:
            for grad in ((F(-3),F(-2)),(F(-1),F(1)),(F(1),F(3))):
                q=quadratic_tangent_min(d,grad)
                for i in range(21):
                    dx=d[0]+(d[1]-d[0])*F(i,20)
                    for j in range(9):
                        g=grad[0]+(grad[1]-grad[0])*F(j,8)
                        self.assertLessEqual(q,g*dx+G*G*dx*dx/2)

    def test_05_point_lower_not_above_reference(self):
        for n in (2,3,4):
            c=[F(v) for v in old.CANDIDATES[n]]
            b=tuple((x,x) for x in c)
            a=precompute_anchors(n)
            lower=scalar_minorant(b,a)
            value=independently_mpmath([mp_f(x) for x in c])
            self.assertLessEqual(mp_f(lower),value)

    def test_06_many_boxes_and_costs(self):
        rng=np.random.default_rng(314159)
        for n in (2,3,4):
            anchors=precompute_anchors(n)
            candidate=[F(s) for s in old.CANDIDATES[n]]
            for _ in range(4):
                mids=[v+F(str(float(s))) for v,s in zip(candidate,rng.uniform(-.5,.5,size=n))]
                radius=F(1,7)
                box=tuple((z-radius,z+radius) for z in mids)
                b=scalar_minorant(box,anchors)
                testpoints=[mids,list(z-radius for z in mids),list(z+radius for z in mids)]
                for point in testpoints:
                    actual=independently_mpmath([mp_f(z) for z in point])
                    self.assertLessEqual(mp_f(b),actual)
                self.assertGreaterEqual(score(box,'risk',anchors),old.cost_bounds(box)[0])
                self.assertGreaterEqual(score(box,'risk_centered',anchors),centered.centered_lower(box))

    def test_07_negative_boxes_and_validation(self):
        for n in (2,3,4):
            b=tuple((F(-3),F(-2)) for _ in range(n))
            for mode in ('risk','risk_centered'):
                score(b,mode,precompute_anchors(n))
        with self.assertRaises(ValueError):quadratic_tangent_min((F(2),F(1)),(F(0),F(1)))
        with self.assertRaises(ValueError):quadratic_tangent_min((F(0),F(1)),(F(2),F(1)))
        with self.assertRaises(ValueError):score(((F(0),F(1)),)*2,'unknown')
        with self.assertRaises(ValueError):precompute_anchors(5)

    def test_08_zero_width_plus_point_equivalence(self):
        for n in (2,3,4):
            theta=[F(s) for s in old.CANDIDATES[n]]
            box=tuple((v,v) for v in theta)
            l0,u0=old.cost_bounds(box)
            l1=score(box,'risk_centered')
            self.assertGreaterEqual(l1,l0)
            self.assertLessEqual(l1,u0)

    def test_09_small_cap_fails_honestly(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as tmp:
            r=cert(4,Path(tmp)/'proof','risk',cap=3)
            self.assertEqual(r['splits'],3)
            self.assertFalse(r['qualifies'])
            self.assertGreater(F(r['regret_upper']),F(1,100))


if __name__=='__main__':unittest.main(verbosity=2)
