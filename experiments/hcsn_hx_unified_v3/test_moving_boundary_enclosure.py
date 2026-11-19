"""Independent density-integral tests of slope-bounded first-hit research."""
import unittest
import mpmath as mp
from experiments.hcsn_hx_unified_v3.moving_boundary_enclosure import (
    linear_boundary_first_hit as hit, slope_bounded_first_hit as env
)

class MovingHitTests(unittest.TestCase):
    def test_density_oracle(self):
        with mp.workdps(80):
            for a,mu,s,c,T,q in [(.3,-.1,.45,.15,.5,.9),(.9,.4,.7,.8,1.5,.2),
                                  (.6,-.7,.35,-.2,1.3,1.2),(1.2,.3,.5,.55,2.8,.03)]:
                F,G=hit(a,0,mu,s,c,T,q,dps=80)
                a,nu,s,T,q=map(mp.mpf,(a,mu-c,s,T,q))
                def f(t):
                    if not t: return mp.mpf(0)
                    return a/(s*mp.sqrt(2*mp.pi*t**3))*mp.exp(-(a+nu*t)**2/(2*s*s*t))
                times=[0,T/8,T/2,T]
                self.assertLess(abs(F-mp.quad(f,times)),mp.mpf('1e-35'))
                self.assertLess(abs(G-mp.quad(lambda t:mp.exp(-q*t)*f(t),times)),mp.mpf('1e-35'))

    def test_frozen_identity(self):
        x=hit(1,0,.05,.6,0,1.3,.3)
        self.assertEqual(x,env(1,0,.05,.6,0,0,1.3,.3).lower)
    def test_moving_is_not_frozen(self):
        frozen=hit(1,0,0,.4,0,1,.2)
        moving=hit(1,0,0,.4,.8,1,.2)
        self.assertGreater(moving.probability-frozen.probability,.3)
        self.assertGreater(moving.discounted,frozen.discounted)
    def test_slope_envelope(self):
        e=env(1,0,0,.4,.1,.3,2,.3)
        m=hit(1,0,0,.4,.2,2,.3)
        self.assertLess(e.lower.probability,m.probability)
        self.assertLess(m.probability,e.upper.probability)
        self.assertLess(e.lower.discounted,m.discounted)
        self.assertLess(m.discounted,e.upper.discounted)
    def test_nesting(self):
        w=env(.8,0,-.1,.5,-.3,.5,2,1)
        n=env(.8,0,-.1,.5,-.1,.3,2,1)
        for f in ('probability','discounted'):
            self.assertLessEqual(getattr(w.lower,f),getattr(n.lower,f))
            self.assertLessEqual(getattr(n.upper,f),getattr(w.upper,f))
    def test_zero_window(self):
        self.assertEqual(hit(1,0,0,.4,.1,0,2).probability,0)
    def test_immediate_event(self):
        for x in (0,-.25): self.assertEqual(hit(x,0,.2,.5,1,0,3).discounted,1)
    def test_zero_discount(self):
        for c in (-1,0,.1,1):
            v=hit(1,0,.3,.6,c,1,0)
            self.assertLess(abs(v.probability-v.discounted),mp.mpf('1e-85'))
    def test_velocity_ordering(self):
        p=hit(.6,0,0,.5,-1,2,.2)
        for c in (-.3,0,.2,.6,1.5):
            z=hit(.6,0,0,.5,c,2,.2)
            self.assertLessEqual(p.probability,z.probability)
            self.assertLessEqual(p.discounted,z.discounted)
            p=z
    def test_tiny_probability(self):
        v=hit(1,0,0,.1,0,.01,.1)
        self.assertGreater(v.probability,0)
        self.assertLess(v.probability,mp.mpf('1e-1000'))
    def test_invalid(self):
        for args in [(1,0,0,0,0,1,0),(1,0,0,.4,0,-1,0),
                     (1,0,0,.4,0,1,-1),(1,0,float('nan'),.4,0,1,0)]:
            with self.assertRaises(ValueError): hit(*args)
        with self.assertRaises(ValueError): env(1,0,0,.4,1,-1,1)
        with self.assertRaises(ValueError): hit(1,0,0,.4,0,1,dps=10)

if __name__ == '__main__': unittest.main()
