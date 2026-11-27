"""R24 mathematical unit tests, independent nested 16-leaf mpmath diagnostics."""
import random
import unittest
from fractions import Fraction as F
import mpmath as mp
import eliminate as e

mp.mp.dps=90

def mpf(x):
    x=F(x)
    return mp.mpf(x.numerator)/x.denominator

def full_16_leaf(theta):
    a,b=theta[:2];c=theta[2] if len(theta)>2 else F(0);d=theta[3] if len(theta)>3 else F(0)
    def q(x,k):return k*mpf(x)/(1+mpf(x)**2)
    total=mp.mpf('0')
    for x in (-1,1):
        h1=mpf(a)*x+mpf(c);v=mpf(a-b)
        common=mpf(b)*h1+mpf(d)*h1**2/4+v*v/4+q(a,e.old.ETA)+q(a-b,e.old.KAPPA)
        for p0 in (0,1):
            outer=[]
            for eps1 in (-1,1):
                p1=p0^(eps1==1)
                inner=[]
                for eps2 in (-1,1):
                    p2=p1^(eps2==1)
                    residual=common+mpf(F(eps2,10))-x-1
                    inner.append(residual**2+mpf(F(p2,50)))
                rho=mp.mpf('.5') if p1==0 else mp.mpf(1)
                y=mp.log((mp.exp(rho*inner[0])+mp.exp(rho*inner[1]))/2)/rho
                outer.append(mpf(F(p1,20))+mpf(e.G)*y)
            rho=mp.mpf('.5') if p0==0 else mp.mpf(1)
            val=mp.log((mp.exp(rho*outer[0])+mp.exp(rho*outer[1]))/2)/rho
            total+=mpf(e.G)*val/4
    return total+sum(mpf(q)**2 for q in theta)/4

class Tests(unittest.TestCase):
    def test_exp_alternating(self):
        for x in (F(0),F(1,10),F(1),F(2),F(50)):
            bounds=e.expminus_point(x)
            truth=mp.exp(-mpf(x))
            self.assertLessEqual(mpf(bounds.lo),truth)
            self.assertGreaterEqual(mpf(bounds.hi),truth)
    def test_log1p(self):
        for x in (F(0),F(1,17),F(1,2),F(1)):
            out=e.log1p_positive_point(x)
            self.assertLessEqual(mpf(out.lo),mp.log(1+mpf(x)))
            self.assertGreaterEqual(mpf(out.hi),mp.log(1+mpf(x)))
    def test_logcosh(self):
        for x in (F(-9),F(-3,5),F(0),F(3,7),F(21,5)):
            q=e.logcosh_point(x)
            self.assertLessEqual(mpf(q.lo),mp.log(mp.cosh(mpf(x))))
            self.assertGreaterEqual(mpf(q.hi),mp.log(mp.cosh(mpf(x))))
    def test_tanh(self):
        for x in (F(-13),F(-1,3),F(0),F(1,2),F(12)):
            q=e.tanh_point(x)
            self.assertLessEqual(mpf(q.lo),mp.tanh(mpf(x)))
            self.assertGreaterEqual(mpf(q.hi),mp.tanh(mpf(x)))
    def test_direct_16_leaf_identity(self):
        r=random.Random(42)
        for n in (2,3,4):
            for _ in range(7):
                th=tuple(F(r.randint(-15,15),10) for _ in range(n))
                direct=full_16_leaf(th)
                # Independent direct analytic logcosh at the exact residual value.
                total=mp.mpf(0)
                for x in (-1,1):
                    z=e.residual_interval(tuple((a,a) for a in th),x)[0]
                    self.assertEqual(z,e.residual_interval(tuple((a,a) for a in th),x)[1])
                    zz=mpf(z);q=[]
                    for p in (0,1):
                        rho=mp.mpf('.5') if p==0 else mp.mpf(1)
                        v=mpf(F(p,20))+mpf(e.G)*(zz**2+mpf(F(1,50))+mp.log(mp.cosh(rho*(zz/5+mpf(F(1-2*p,100)))))/rho)
                        q.append(v)
                    for p0 in (0,1):
                        rho=mp.mpf('.5') if p0==0 else mp.mpf(1)
                        total+=mpf(e.G)*mp.log((mp.exp(rho*q[0])+mp.exp(rho*q[1]))/2)/rho/4
                        fv=e.scalar_F(z,p0)[0]
                        self.assertLessEqual(mpf(fv.lo),mpf(e.G)*mp.log((mp.exp(rho*q[0])+mp.exp(rho*q[1]))/2)/rho)
                        self.assertGreaterEqual(mpf(fv.hi),mpf(e.G)*mp.log((mp.exp(rho*q[0])+mp.exp(rho*q[1]))/2)/rho)
                total+=sum(mpf(v)**2 for v in th)/4
                self.assertLess(abs(total-direct),mp.mpf('1e-75'))
    def test_derivative_enclosure(self):
        for p in (0,1):
            for z in (F(-2),F(-1,2),F(0),F(2,5),F(4)):
                g=e.scalar_F(z,p)[1]
                eps=mp.mpf('1e-30')
                def v(u):
                    inner=[]
                    for k in (0,1):
                        rho=mp.mpf('.5') if k==0 else mp.mpf(1)
                        inner.append(mpf(F(k,20))+mpf(e.G)*(u*u+mpf(F(1,50))+mp.log(mp.cosh(rho*(u/5+mpf(F(1-2*k,100)))))/rho))
                    rho=mp.mpf('.5') if p==0 else mp.mpf(1)
                    return mpf(e.G)*mp.log((mp.exp(rho*inner[0])+mp.exp(rho*inner[1]))/2)/rho
                dg=mp.diff(v,mpf(z))
                self.assertLessEqual(mpf(g.lo),dg)
                self.assertGreaterEqual(mpf(g.hi),dg)
    def test_strong_convex_lower(self):
        for p in (0,1):
            for center in (F(-2),F(0),F(3,4)):
                for delta in (F(-7,8),F(0),F(9,7)):
                    q,g=e.scalar_F(center,p)
                    tgt=e.scalar_F(center+delta,p)[0]
                    tangent=q.lo+min(g.lo*delta,g.hi*delta)+e.M*delta**2/2
                    self.assertLessEqual(tangent,tgt.lo)
    def test_old_hybrid_dominance(self):
        for n in (2,3,4):
            for z in (F(-1),F(0),F(1)):
                b=tuple((z-F(1,7),z+F(1,7)) for _ in range(n))
                self.assertGreaterEqual(e.hybrid_lower(b),e.c.hybrid_lower(b))
    def test_box_point_lower(self):
        r=random.Random(27)
        for n in (2,3,4):
            for _ in range(10):
                pt=tuple(F(r.randrange(-9,10),10) for _ in range(n))
                box=tuple((v-F(1,5),v+F(1,5)) for v in pt)
                proof=e.hybrid_lower(box)
                tgt=full_16_leaf(pt)
                self.assertLessEqual(mpf(proof),tgt)
    def test_rational_cap(self):
        self.assertEqual(e.old.NODE_CAP,4000)
        self.assertEqual(e.old.TARGET,F(1,100))
        self.assertEqual(len(e.GRID),33)

if __name__=='__main__':unittest.main(verbosity=2)
