"""Bounded, executable, adversarial tests for the two-cell RESEARCH QVI.

No full HX viability, low precision/GPU, trained neural task, or continuum
certification is established by passing these finite-grid tests.
"""
import math
import random
import unittest

import numpy as np

from .stopping import Stop
from .coupled_qvi import (Rectangle, TwoCell, solve_coupled_policy,
                          solve_coupled_jacobi)


P = TwoCell(Stop(.035,.45,.16,1.,0.,.4), Stop(-.02,.42,.16,1.1,-.1,.6))
R = Rectangle(-2.,4.5,21,-2.,4.5,21)


def independent_qvi_residual(p, r, result):
    """Check directly by scalar loops, without calling solver's QVI helpers."""
    v=result.values
    xs=(result.x1,result.x2)
    ds=[]
    for c,x in zip((p.first,p.second),xs):
        h=float(x[1]-x[0]); q=.5*c.diffusion**2/h**2
        qm=q-c.drift/(2*h); qp=q+c.drift/(2*h)
        if min(qm,qp)<0:
            qm=q+max(-c.drift,0.)/h
            qp=q+max(c.drift,0.)/h
        ds.append((qm,qp))
    max_resid=0.
    policy_resid=0.
    for i,x in enumerate(xs[0]):
        for j,y in enumerate(xs[1]):
            # Independently calculate the reflected finite-state CTMC
            # generator; blocked outward transitions contribute zero.
            jumps=[]
            if i>0: jumps.append((ds[0][0],v[i-1,j]))
            if i+1<len(xs[0]): jumps.append((ds[0][1],v[i+1,j]))
            if j>0: jumps.append((ds[1][0],v[i,j-1]))
            if j+1<len(xs[1]): jumps.append((ds[1][1],v[i,j+1]))
            generator=sum(q*(z-v[i,j]) for q,z in jumps)-p.first.discount*v[i,j]
            r1=np.interp(p.first.reset,xs[0],v[:,j])
            r2=np.interp(p.second.reset,xs[1],v[i,:])
            a1=x-p.first.cost+math.exp(-p.first.discount*p.first.refractory)*r1-v[i,j]
            a2=y-p.second.cost+math.exp(-p.second.discount*p.second.refractory)*r2-v[i,j]
            max_resid=max(max_resid,abs(max(generator,a1,a2)))
            action=int(result.policy[i,j])
            policy_resid=max(policy_resid,abs((generator,a1,a2)[action]))
    return max_resid,policy_resid


def simulate_fixed_policy(p: TwoCell, result, start: tuple[int,int], rng: random.Random):
    """Independent event-driven CTMC rollout; no solver transition helpers.

    At 'wait' sample a continuous exponential holding time and one Markov
    transition. At 'fire' pay its reward, freeze during fixed refractory,
    and sample a reset grid index using convex interpolation probabilities.
    """
    grids=(result.x1,result.x2)
    rates=[]; resets=[]
    for c,x in zip((p.first,p.second),grids):
        h=x[1]-x[0]
        d=.5*(c.diffusion/h)**2
        qm=d-c.drift/(2*h); qp=d+c.drift/(2*h)
        if min(qm,qp)<0:
            qm=d+max(-c.drift,0.)/h
            qp=d+max(c.drift,0.)/h
        rates.append((qm,qp))
        k=min(int(np.searchsorted(x,c.reset,side='right')-1),len(x)-2)
        w=(c.reset-x[k])/(x[k+1]-x[k])
        resets.append((k,w))
    i,j=start
    discount=1.; total_reward=0.
    for step in range(5000):
        if discount<1e-9:
            return total_reward
        action=int(result.policy[i,j])
        if action:
            idx=action-1; c=(p.first,p.second)[idx]
            total_reward+=discount*((grids[idx][i] if idx==0 else grids[idx][j])-c.cost)
            discount*=math.exp(-c.discount*c.refractory)
            k,w=resets[idx]
            reset_index=k+int(rng.random()<w)
            if idx==0:i=reset_index
            else:j=reset_index
            continue
        steps=[]
        qm,qp=rates[0]
        if i>0:steps.append((qm,i-1,j))
        if i+1<len(grids[0]):steps.append((qp,i+1,j))
        qm,qp=rates[1]
        if j>0:steps.append((qm,i,j-1))
        if j+1<len(grids[1]):steps.append((qp,i,j+1))
        lam=sum(t[0] for t in steps)
        discount*=math.exp(-p.first.discount*rng.expovariate(lam))
        pick=rng.random()*lam
        for rate, ni, nj in steps:
            pick-=rate
            if pick<=0:
                i,j=ni,nj
                break
    raise AssertionError('Simulated policy path exceeded episode budget')


class TwoCellQviTests(unittest.TestCase):
    def test_independent_sparse_vs_jacobi_three_grids(self):
        for n in (13,21,33):
            with self.subTest(nodes=n):
                rect=Rectangle(-2.,4.5,n,-2.,4.5,n)
                a=solve_coupled_policy(P,rect)
                b=solve_coupled_jacobi(P,rect)
                self.assertLess(float(np.max(abs(a.values-b.values))),2e-8)
                self.assertLess(a.bellman_residual,3e-12)
                self.assertLess(a.generator_qvi_residual,3e-12)
                self.assertLess(b.bellman_residual,2.5e-10)
                self.assertTrue({0,1,2}.issubset(set(np.unique(a.policy))))
                self.assertGreater(b.iterations,a.iterations)

    def test_independently_recomputed_qvi_and_action_complementarity(self):
        a=solve_coupled_policy(P,R)
        resid,active=independent_qvi_residual(P,R,a)
        self.assertLess(resid,5e-12)
        self.assertLess(active,5e-12)
        self.assertTrue(np.all(a.values>=-1e-12))
        for axis in (0,1):
            self.assertTrue(np.min(np.diff(a.values,axis=axis))>=-1e-10)

    def test_order_invariance_when_cells_are_swapped(self):
        p=TwoCell(P.second,P.first)
        r=Rectangle(R.x2min,R.x2max,R.n2,R.x1min,R.x1max,R.n1)
        a=solve_coupled_policy(P,R)
        b=solve_coupled_policy(p,r)
        self.assertLess(float(np.max(abs(a.values-b.values.T))),3e-11)
        self.assertEqual(sum(a.policy.ravel()==1),sum(b.policy.ravel()==2))
        self.assertEqual(sum(a.policy.ravel()==2),sum(b.policy.ravel()==1))

    def test_symmetric_configuration_is_symmetric(self):
        s=Stop(.0,.37,.22,1.,.0,.5)
        p=TwoCell(s,s)
        a=solve_coupled_policy(p,Rectangle(-2.5,3.5,25,-2.5,3.5,25))
        self.assertLess(float(np.max(abs(a.values-a.values.T))),1e-11)
        self.assertEqual(set(np.unique(a.policy)),{0,1,2})

    def test_no_positive_exercise_returns_zero_baseline(self):
        # Both rewards are strictly negative on the full rectangle, while a
        # reset cannot create an arbitrage cycle because delay discount < 1.
        p=TwoCell(Stop(.07,.35,.2,100.,0.,.5),Stop(-.01,.4,.2,100.,0.,.1))
        g=Rectangle(-3.,5.,17,-3.,5.,21)
        a=solve_coupled_policy(p,g)
        b=solve_coupled_jacobi(p,g)
        self.assertTrue(np.all(a.policy==0))
        self.assertTrue(np.all(a.values==0))
        self.assertTrue(np.all(b.values==0))

    def test_inert_cell_reduces_to_single_dimension(self):
        a=TwoCell(Stop(.0,.4,.2,1.,0.,.3),Stop(.03,.37,.2,100.,0.,.6))
        grid=Rectangle(-2.5,3.5,25,-3.5,4.5,17)
        out=solve_coupled_policy(a,grid)
        self.assertLess(float(np.max(np.ptp(out.values,axis=1))),3e-12)
        self.assertFalse(np.any(out.policy==2))
        # Independently solve a 1D reflected CTMC Bellman equation, with
        # no use of either the 2D QVI solver's generator or its policy.
        x=np.linspace(grid.x1min,grid.x1max,grid.n1)
        h=x[1]-x[0]
        q=.5*a.first.diffusion**2/h**2
        v=np.zeros(grid.n1)
        for _ in range(30000):
            next_v=np.zeros_like(v)
            reset=float(np.interp(a.first.reset,x,v))
            for i, xi in enumerate(x):
                l=q if i else 0.
                u=q if i<grid.n1-1 else 0.
                cont=((l*v[i-1] if i else 0.)+
                      (u*v[i+1] if i<grid.n1-1 else 0.))/(a.first.discount+l+u)
                fire=xi-a.first.cost+a.first.delay_discount*reset
                next_v[i]=max(cont,fire)
            if np.max(abs(next_v-v))<1e-12:
                v=next_v
                break
            v=next_v
        self.assertLess(float(np.max(abs(out.values[:,5]-v))),2e-11)

    def test_refinement_value_converges_in_selected_case(self):
        p=TwoCell(Stop(.0,.38,.2,1.,0.,.6),Stop(.0,.38,.2,1.,0.,.6))
        samples=[]
        for n in (17,33,65):
            r=Rectangle(-3.,4.,n,-3.,4.,n)
            samples.append(solve_coupled_policy(p,r).at(.5,.5))
        self.assertLess(abs(samples[2]-samples[1]),abs(samples[1]-samples[0]))
        self.assertLess(abs(samples[2]-samples[1]),.01)

    def test_advection_dominated_upwind_branch_is_monotone(self):
        p=TwoCell(Stop(.85,.08,.3,1.,0.,.4),Stop(-.75,.07,.3,1.,0.,.5))
        r=Rectangle(-2.,3.,17,-2.,3.,17)
        a=solve_coupled_policy(p,r)
        b=solve_coupled_jacobi(p,r)
        self.assertLess(float(np.max(abs(a.values-b.values))),2e-8)
        self.assertLess(a.generator_qvi_residual,5e-12)

    def test_off_grid_reset_and_bilinear_query(self):
        p=TwoCell(Stop(.03,.43,.18,1.,.1137,.3), Stop(-.02,.51,.18,1.1,-.237,.7))
        r=Rectangle(-2.1,3.9,23,-1.9,4.3,19)
        a=solve_coupled_policy(p,r)
        self.assertLess(a.generator_qvi_residual,1e-10)
        for reset in a.reset_interpolations:
            self.assertAlmostEqual(sum(w for _,w in reset),1.,places=13)
            self.assertTrue(all(0<=w<=1 for _,w in reset))
        i,j=4,5
        for k,z in [(a.x1[i],a.x2[j]),(a.x1[-1],a.x2[-1])]:
            self.assertAlmostEqual(a.at(k,z),float(np.interp(z,a.x2,
                                  np.array([np.interp(k,a.x1,a.values[:,u])
                                            for u in range(len(a.x2))]))),places=11)
        with self.assertRaises(ValueError):a.at(float('nan'),0.)
        with self.assertRaises(ValueError):a.at(100.,0.)

    def test_independent_event_driven_monte_carlo_policy_value(self):
        a=solve_coupled_policy(P,Rectangle(-2.,4.5,13,-2.,4.5,13))
        rng=random.Random(20261030)
        for state in ((8,8),(6,6)):
            rolls=np.array([simulate_fixed_policy(P,a,state,rng) for _ in range(2500)])
            std_err=float(np.std(rolls,ddof=1)/math.sqrt(len(rolls)))
            # A statistical check, not a deterministic mathematical proof.
            self.assertLess(abs(float(np.mean(rolls))-float(a.values[state])),
                            max(.035,6*std_err))

    def test_seeded_robust_policy_parameter_sweep(self):
        rng=random.Random(20261030)
        worst=0.
        for k in range(90):
            rho=rng.uniform(.15,.5)
            p=TwoCell(Stop(rng.uniform(-.15,.2),rng.uniform(.16,.75),rho,
                           rng.uniform(.7,1.4),rng.uniform(-.4,.1),rng.uniform(.2,1.5)),
                      Stop(rng.uniform(-.15,.2),rng.uniform(.16,.75),rho,
                           rng.uniform(.7,1.4),rng.uniform(-.4,.1),rng.uniform(.2,1.5)))
            r=Rectangle(-2.1,3.6,13,-2.2,3.8,15)
            a=solve_coupled_policy(p,r)
            worst=max(worst,a.generator_qvi_residual)
            self.assertLess(a.generator_qvi_residual,2e-11)
            self.assertGreaterEqual(float(np.min(a.values)),-1e-12)
            if k%15==0:
                b=solve_coupled_jacobi(p,r)
                self.assertLess(float(np.max(abs(a.values-b.values))),4e-9)
        self.assertLess(worst,2e-11)

    def test_invalid_inputs_and_budget_fail_closed(self):
        cases=[
            (TwoCell(Stop(0.,.4,.2,1.,0.,0.),P.second),R),
            (TwoCell(Stop(0.,.4,.2,1.,0.,1e-50),P.second),R),
            (TwoCell(P.first,Stop(0.,.4,.4,1.,0.,.5)),R),
            (P,Rectangle(-2.,4.,True,-2.,4.,21)),
            (P,Rectangle(-2.,4.,8,-2.,4.,21)),
            (P,Rectangle(-2.,4.,97,-2.,4.,97)),
            (P,Rectangle(float('nan'),4.,21,-2.,4.,21)),
            (P,Rectangle(0.,4.,21,-2.,4.,21)),
            (P,Rectangle(-2.,4.,21,0.,4.,21)),
            (P,Rectangle(-2.,-3.,21,-2.,4.,21)),
        ]
        for p,r in cases:
            with self.subTest(p=p,r=r),self.assertRaises((ValueError,ArithmeticError)):
                solve_coupled_policy(p,r)
        with self.assertRaises(TypeError):solve_coupled_policy(None,R)
        with self.assertRaises(ValueError):solve_coupled_jacobi(P,R,tolerance=0.)
        with self.assertRaises(ValueError):solve_coupled_policy(P,R,max_iterations=0)
        with self.assertRaises(ValueError):solve_coupled_policy(P,R,decision_tolerance=float('nan'))
        with self.assertRaises(RuntimeError):solve_coupled_jacobi(P,R,max_iterations=1)
        with self.assertRaises(RuntimeError):solve_coupled_policy(P,R,max_iterations=1)

if __name__=='__main__':unittest.main()
