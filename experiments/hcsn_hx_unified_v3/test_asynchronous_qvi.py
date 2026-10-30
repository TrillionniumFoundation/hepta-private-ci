"""Independent verification of a BOUNDED research-only asynchronous two-cell CTMC.

No HX financial all-domain result, deterministic refractory, continuum limit,
precision certificate, neural memory task, 64+ cell scalability, or P1-P5 gain.
"""
import math
import random
import unittest

import numpy as np

from .stopping import Stop
from .coupled_qvi import Rectangle, TwoCell, solve_coupled_policy
from .asynchronous_qvi import (solve_asynchronous_policy,
                               solve_asynchronous_jacobi)


P = TwoCell(Stop(.035,.45,.16,1.,0.,.4),Stop(-.02,.42,.16,1.1,-.1,.6))
R = Rectangle(-2.,4.5,13,-2.,4.5,13)


def _rates(stop:Stop,x):
    """Independent scalar finite CTMC rate formula, including upwind."""
    h=float(x[1]-x[0]); d=stop.diffusion**2/(2*h**2)
    minus=d-stop.drift/(2*h); plus=d+stop.drift/(2*h)
    if min(minus,plus)<0:
        minus=d+max(-stop.drift,0)/h
        plus=d+max(stop.drift,0)/h
    return minus,plus


def independent_qvi_residual(p,result):
    """Pure scalar loops: no generator/action/residual helper from implementation."""
    n,m=len(result.x1),len(result.x2)
    x,y=result.x1,result.x2
    v=result.values
    mx=0.; chosen=0.; min_margin=math.inf
    a=_rates(p.first,x); b=_rates(p.second,y)
    for i in range(n+1):
        for j in range(m+1):
            edges=[]
            if i<n:
                if i>0: edges.append((a[0],v[i-1,j]))
                if i<n-1: edges.append((a[1],v[i+1,j]))
            else:
                edges.append((1/p.first.refractory,np.interp(p.first.reset,x,v[:n,j])))
            if j<m:
                if j>0: edges.append((b[0],v[i,j-1]))
                if j<m-1: edges.append((b[1],v[i,j+1]))
            else:
                edges.append((1/p.second.refractory,np.interp(p.second.reset,y,v[i,:m])))
            generator=sum(rate*(next_v-v[i,j]) for rate,next_v in edges)-p.first.discount*v[i,j]
            f1=x[i]-p.first.cost+v[n,j]-v[i,j] if i<n else -math.inf
            f2=y[j]-p.second.cost+v[i,m]-v[i,j] if j<m else -math.inf
            residuals=[generator,f1,f2]
            mx=max(mx,abs(max(residuals)))
            chosen=max(chosen,abs(residuals[int(result.policy[i,j])]))
            min_margin=min(min_margin, min(v[i,j],v[i,j]-f1,v[i,j]-f2))
    return mx,chosen,min_margin


def scalar_exponential_refractory(stop:Stop,x:np.ndarray):
    """One-cell independent renewal Bellman grid, entirely separately written."""
    n=len(x)
    minus,plus=_rates(stop,x)
    lam=1/stop.refractory
    v=np.zeros(n+1)
    for _ in range(80000):
        w=np.zeros(n+1)
        for i in range(n):
            qdown=minus if i>0 else 0.
            qup=plus if i<n-1 else 0.
            cont=((qdown*v[i-1] if i>0 else 0.)+
                  (qup*v[i+1] if i<n-1 else 0.))/(stop.discount+qdown+qup)
            w[i]=max(cont,x[i]-stop.cost+v[n])
        w[n]=lam*np.interp(stop.reset,x,v[:n])/(stop.discount+lam)
        if np.max(np.abs(w-v))<5e-13:
            return w
        v=w
    raise AssertionError('Scalar oracle failed to converge')


def monte_carlo_independent(p,result,start,seed,n_episodes=1600):
    """Seeded continuous-time Gillespie simulation of the *chosen fixed policy*.

    This is an independent event sampler, not the policy solver or Jacobi.
    Holding times are exponentially sampled from actual CTMC rates. Recovery
    is sampled independently for each refractory cell, other cell still moves.
    """
    rng=random.Random(seed)
    x,y=result.x1,result.x2
    n,m=len(x),len(y)
    a=_rates(p.first,x); b=_rates(p.second,y)
    stops=(p.first,p.second)
    coords=(x,y)
    samples=[]
    for episode in range(n_episodes):
        i,j=start
        discount=1.; total=0.
        for step in range(10000):
            if discount<1e-10:
                break
            act=int(result.policy[i,j])
            if act:
                which=act-1
                c=stops[which]
                old=i if which==0 else j
                total+=discount*(coords[which][old]-c.cost)
                if which==0:
                    assert i<n
                    i=n
                else:
                    assert j<m
                    j=m
                continue
            edges=[]
            if i<n:
                if i>0:edges.append((a[0],(i-1,j)))
                if i<n-1:edges.append((a[1],(i+1,j)))
            else:
                rate=1/p.first.refractory
                k=min(int(np.searchsorted(x,p.first.reset,side='right'))-1,n-2)
                w=(p.first.reset-x[k])/(x[k+1]-x[k])
                edges.extend(((rate*(1-w),(k,j)),(rate*w,(k+1,j))))
            if j<m:
                if j>0:edges.append((b[0],(i,j-1)))
                if j<m-1:edges.append((b[1],(i,j+1)))
            else:
                rate=1/p.second.refractory
                k=min(int(np.searchsorted(y,p.second.reset,side='right'))-1,m-2)
                w=(p.second.reset-y[k])/(y[k+1]-y[k])
                edges.extend(((rate*(1-w),(i,k)),(rate*w,(i,k+1))))
            rate=sum(z for z,_ in edges)
            if rate<=0:
                break
            dt=rng.expovariate(rate)
            discount*=math.exp(-p.first.discount*dt)
            uniform=rng.random()*rate
            for transition_rate,(ii,jj) in edges:
                uniform-=transition_rate
                if uniform<=0:
                    i,j=ii,jj
                    break
            else:
                i,j=edges[-1][1]
        else:
            raise AssertionError('Monte Carlo exceeded 10000 events')
        samples.append(total)
    avg=float(np.mean(samples)); stderr=float(np.std(samples,ddof=1)/math.sqrt(n_episodes))
    return avg,stderr


class AsynchronousQviTests(unittest.TestCase):
    def test_two_independent_solver_families(self):
        configs=[
            (P,R),
            (TwoCell(Stop(.8,.25,.3,1.,-.4,.5),Stop(-.6,.2,.3,.9,-.6,1.2)),
             Rectangle(-2.5,3.8,9,-2.3,4.1,11)),
            (TwoCell(Stop(-.2,.8,.22,1.5,-.1,2.),Stop(.35,.9,.22,.5,-1.,.1)),
             Rectangle(-3.,5.,11,-3.,4.,9)),
            (TwoCell(Stop(0.,.3,.4,1.,.1,.01),Stop(0.,.2,.4,.9,.05,2.)),
             Rectangle(-2.,2.,9,-2.,2.,9)),
        ]
        for p,r in configs:
            with self.subTest(p=p):
                policy=solve_asynchronous_policy(p,r)
                jacobi=solve_asynchronous_jacobi(p,r)
                self.assertLess(float(np.max(np.abs(policy.values-jacobi.values))),1.5e-8)
                self.assertLess(policy.qvi_residual,2e-8)
                self.assertLess(jacobi.qvi_residual,3e-8)
                self.assertFalse(np.any(policy.policy[-1,:]==1))
                self.assertFalse(np.any(policy.policy[:,-1]==2))

    def test_scalar_independent_residual(self):
        result=solve_asynchronous_policy(P,R)
        residual,chosen,margin=independent_qvi_residual(P,result)
        self.assertLess(residual,1e-9)
        self.assertLess(chosen,1e-9)
        self.assertGreaterEqual(margin,-1e-9)

    def test_other_cell_keeps_evolving_and_can_fire_in_refractory(self):
        result=solve_asynchronous_policy(P,R)
        n,m=len(result.x1),len(result.x2)
        self.assertTrue(np.any(result.policy[n,:m]==2))
        self.assertTrue(np.any(result.policy[:n,m]==1))
        self.assertGreater(result.values[n,m],0.)
        self.assertGreater(np.ptp(result.values[n,:m]),.1)
        self.assertGreater(np.ptp(result.values[:n,m]),.1)

    def test_not_equivalent_to_global_freeze_with_deterministic_delay(self):
        frozen=solve_coupled_policy(P,R)
        async_result=solve_asynchronous_policy(P,R)
        diff=float(np.max(np.abs(frozen.values-async_result.values[:-1,:-1])))
        self.assertGreater(diff,.02)
        # Models intentionally have different refractory distributions and
        # global vs per-cell dynamics; this is NOT a superiority comparison.

    def test_inert_first_cell_matches_independently_programmed_scalar_model(self):
        p=TwoCell(Stop(.035,.45,.16,1e5,0.,.4),P.second)
        result=solve_asynchronous_policy(p,R)
        self.assertFalse(np.any(result.policy==1))
        scalar=scalar_exponential_refractory(p.second,result.x2)
        np.testing.assert_allclose(result.values,
                                  np.broadcast_to(scalar[None,:],result.values.shape),
                                  rtol=0.,atol=1e-8)

    def test_inert_both_cells_zero(self):
        p=TwoCell(Stop(.1,.4,.16,1e5,0.,.4),Stop(-.1,.5,.16,1e5,-.1,.6))
        result=solve_asynchronous_policy(p,R)
        self.assertTrue(np.all(result.policy==0))
        self.assertLess(float(np.max(np.abs(result.values))),1e-12)

    def test_swap_and_equal_cell_symmetry(self):
        p=TwoCell(P.second,P.first)
        r=Rectangle(R.x2min,R.x2max,R.n2,R.x1min,R.x1max,R.n1)
        u=solve_asynchronous_policy(P,R)
        v=solve_asynchronous_policy(p,r)
        np.testing.assert_allclose(u.values,v.values.T,atol=1e-9,rtol=0.)
        c=Stop(.1,.55,.2,1.,0.,.7)
        square=Rectangle(-2.,4.,11,-2.,4.,11)
        same=solve_asynchronous_policy(TwoCell(c,c),square)
        np.testing.assert_allclose(same.values,same.values.T,atol=1e-9,rtol=0.)

    def test_two_rapid_distinct_fires_are_allowed(self):
        # Negligible motion after reset: one immediate profitable fire of
        # *each* initially high cell, with NO global refractory freeze.
        p=TwoCell(Stop(0.,1e-7,.2,1.,-.5,1.),Stop(0.,1e-7,.2,.9,-.6,.5))
        r=Rectangle(-2.,3.,9,-2.,3.,9)
        out=solve_asynchronous_policy(p,r)
        self.assertAlmostEqual(out.values[0,0],0.,delta=1e-6)
        self.assertAlmostEqual(out.values[-1,-1],0.,delta=1e-6)
        self.assertAlmostEqual(out.values[8,8],(3.-1.)+(3.-.9),delta=1e-7)
        self.assertIn(out.policy[8,8],(1,2))
        self.assertEqual(int(out.policy[9,8]),2)
        self.assertEqual(int(out.policy[8,9]),1)

    def test_event_driven_monte_carlo_of_policy(self):
        r=Rectangle(-2.,4.,9,-2.,4.,9)
        out=solve_asynchronous_policy(P,r)
        for index,start in enumerate(((8,8),(len(out.x1),5),(5,len(out.x2)),
                                      (len(out.x1),len(out.x2)))):
            with self.subTest(start=start):
                avg,se=monte_carlo_independent(P,out,start,seed=5200+index,n_episodes=1000)
                expected=out.values[start]
                self.assertLess(abs(avg-expected),5.5*se+.025)

    def test_selected_grid_refinement_without_continuum_claim(self):
        # One selected case only: not a uniform free-boundary error bound.
        values=[]
        for n in (9,17,33,65):
            r=Rectangle(-2.,4.5,n,-2.,4.5,n)
            out=solve_asynchronous_policy(P,r)
            self.assertLess(out.qvi_residual,1e-9)
            values.append(out.at_active(.5,.5))
        deltas=np.abs(np.diff(values))
        self.assertTrue(all(deltas[i+1]<deltas[i] for i in range(len(deltas)-1)))
        self.assertLess(deltas[-1],.002)

    def test_seeded_bounded_configurations(self):
        rng=random.Random(84421)
        for _ in range(32):
            rho=rng.uniform(.09,.7)
            c1=Stop(rng.uniform(-1.,1.),rng.uniform(.15,.8),rho,
                    rng.uniform(.5,2.0),-.3,rng.uniform(.06,3.))
            c2=Stop(rng.uniform(-1.,1.),rng.uniform(.15,.8),rho,
                    rng.uniform(.5,2.0),-.5,rng.uniform(.06,3.))
            p=TwoCell(c1,c2)
            r=Rectangle(-2.5,3.5,9,-2.5,3.5,9)
            out=solve_asynchronous_policy(p,r)
            residual,chosen,_=independent_qvi_residual(p,out)
            self.assertLess(residual,2e-8)
            self.assertLess(chosen,2e-8)

    def test_input_and_precision_fail_closed(self):
        for p,r in (
            (TwoCell(Stop(0.,.5,.2,1.,0.,0.),P.second),R),
            (P,Rectangle(-2.,4.,8,-2.,4.,9)),
            (P,Rectangle(-2.,4.,9,-2.,4.,100)),
            (P,Rectangle(-2.,4.,9,-2.,4.,9.5)),
        ):
            with self.subTest(p=p,r=r),self.assertRaises((ValueError,TypeError)):
                solve_asynchronous_policy(p,r)
        huge=TwoCell(Stop(0.,1e15,.16,1.,0.,.4),P.second)
        with self.assertRaises(ArithmeticError):
            solve_asynchronous_policy(huge,R)
        with self.assertRaises(ValueError):
            solve_asynchronous_policy(P,R,decision_tolerance=math.nan)
        with self.assertRaises(ValueError):
            solve_asynchronous_jacobi(P,R,tolerance=0.)
        with self.assertRaises(RuntimeError):
            solve_asynchronous_policy(P,R,max_iterations=1)
        with self.assertRaises(RuntimeError):
            solve_asynchronous_jacobi(P,R,max_iterations=1)
        out=solve_asynchronous_policy(P,R)
        for x,y in ((math.nan,0.),(0.,math.inf),(-99.,1.),(1.,99.)):
            with self.assertRaises(ValueError):
                out.at_active(x,y)


if __name__ == "__main__":
    unittest.main()
