"""Independent stationary regenerative QVI discretization tests.

These tests check bounded finite grids, not a continuum/global proof, and do
not certify He--Xiong's distinct financial model or HCSN training/production.
"""
import math
import random
import unittest

import numpy as np

from .regenerative_grid import Grid, solve_policy, solve_value_iteration
from .stopping import Stop, regenerative_value, regenerative_boundary, one_shot_value, one_shot_boundary


CASES = (
    Stop(drift=.04,diffusion=.5,discount=.15,cost=1.,reset=0.,refractory=.2),
    Stop(drift=-.11,diffusion=.6,discount=.12,cost=1.,reset=-.15,refractory=.5),
    Stop(drift=0.,diffusion=.3,discount=.3,cost=1.,reset=0.,refractory=0.),
)


class RegenerativeGridTests(unittest.TestCase):
    def test_independent_policy_vs_jacobi_and_qvi(self):
        for p in CASES:
            with self.subTest(p=p):
                grid=Grid(-10.,6.,129)
                a=solve_policy(p,grid)
                b=solve_value_iteration(p,grid)
                self.assertLess(np.max(np.abs(a.values-b.values)),4e-9)
                self.assertLess(a.residual,1e-9)
                self.assertLess(b.residual,3e-11)
                self.assertTrue(a.fire[-1])
                self.assertFalse(a.fire[0])
                self.assertGreaterEqual(np.min(a.values),-1e-11)
                self.assertTrue(np.all(np.diff(a.values)>=-1e-10))
                self.assertGreater(b.iterations,a.iterations)
                # Independent reference threshold, not supplied to the solver.
                self.assertLess(abs(a.boundary_high-regenerative_boundary(p)),.25)

    def test_grid_refinement_and_analytic_value_outside_boundary(self):
        for p in CASES:
            with self.subTest(p=p):
                coarse=solve_policy(p,Grid(-10.,6.,257))
                fine=solve_policy(p,Grid(-10.,6.,1025))
                points=[p.reset-.75,p.reset,p.cost-.4,p.cost,p.cost+1.]
                errors_coarse=[abs(coarse.at(z)-regenerative_value(p,z)) for z in points]
                errors_fine=[abs(fine.at(z)-regenerative_value(p,z)) for z in points]
                self.assertLess(max(errors_fine),1e-4)
                self.assertLess(sum(errors_fine),.45*sum(errors_coarse))
                self.assertLess(abs(fine.boundary_high-regenerative_boundary(p)),.04)
                self.assertLess(max(fine.boundary_high-fine.boundary_low,0),.016)

    def test_derivative_and_generator_residual_recomputed(self):
        for p in CASES:
            out=solve_policy(p,Grid(-10.,6.,257))
            x=out.x; v=out.values; h=x[1]-x[0]
            diff=.5*p.diffusion*p.diffusion/(h*h)
            left=diff-p.drift/(2*h)
            right=diff+p.drift/(2*h)
            if min(left,right)<0:
                left=diff+max(-p.drift,0)/h
                right=diff+max(p.drift,0)/h
            rv=out.at(p.reset)
            generator=left*v[:-2]-(left+right+p.discount)*v[1:-1]+right*v[2:]
            obstacle=x[1:-1]-p.cost+p.delay_discount*rv-v[1:-1]
            self.assertLess(float(np.max(np.maximum(generator,obstacle))),1e-9)
            self.assertLess(float(np.max(np.abs(np.maximum(generator,obstacle)))),1e-9)
            fired=out.fire[1:-1]
            self.assertLess(float(np.max(np.abs(obstacle[fired]))),1e-9)
            self.assertLess(float(np.max(np.abs(generator[~fired]))),1e-9)
            # Continuum smooth pasting is NOT pointwise exact on a finite grid.
            # Measured one-sided mesh slopes approach 1 near boundary.
            i=int(np.flatnonzero(out.fire)[0])
            left_slope=(v[i]-v[i-1])/h
            self.assertLess(abs(left_slope-1),.1)
            finer=solve_policy(p,Grid(-10.,6.,1025))
            k=int(np.flatnonzero(finer.fire)[0])
            fine_slope=(finer.values[k]-finer.values[k-1])/(finer.x[k]-finer.x[k-1])
            self.assertLess(abs(fine_slope-1),abs(left_slope-1))
            self.assertLess(abs(fine_slope-1),.04)

    def test_finite_domain_lower_wall_convergence(self):
        p=CASES[0]
        g1=solve_policy(p,Grid(-5.,6.,449))
        g2=solve_policy(p,Grid(-10.,6.,641))
        g3=solve_policy(p,Grid(-15.,6.,841))
        a=regenerative_value(p,0.5)
        self.assertLess(abs(g3.at(.5)-a),abs(g1.at(.5)-a))
        self.assertLess(abs(g3.at(.5)-g2.at(.5)),1e-5)

    def test_large_refractory_recovers_one_shot_stopping(self):
        p=Stop(.04,.5,.15,1.,0.,100.)
        out=solve_policy(p,Grid(-10.,6.,1025))
        self.assertLess(abs(out.boundary_high-one_shot_boundary(p)),.03)
        for x in [-1.,0.,.7,1.5,2.5]:
            self.assertLess(abs(out.at(x)-one_shot_value(p,x)),7e-5)

    def test_non_grid_aligned_reset_preserves_convex_weights(self):
        p=Stop(.045,.41,.18,1.,.1273,.4)
        g=Grid(-7.13,5.84,325)
        out=solve_policy(p,g)
        self.assertAlmostEqual(sum(w for _,w in out.interpolation_weights),1.,places=12)
        self.assertTrue(all(0<=w<=1 for _,w in out.interpolation_weights))
        self.assertLess(abs(out.at(p.reset)-regenerative_value(p,p.reset)),.0005)
        self.assertLess(abs(out.boundary_high-regenerative_boundary(p)),.08)

    def test_seeded_bounded_parameter_sweep(self):
        rng=random.Random(20261030)
        for _ in range(36):
            p=Stop(drift=rng.uniform(-.15,.2), diffusion=rng.uniform(.2,.75),
                   discount=rng.uniform(.09,.35),cost=rng.uniform(.6,1.4),
                   reset=rng.uniform(-.4,.2),refractory=rng.uniform(0,2))
            grid=Grid(-12.,7.,257)
            a=solve_policy(p,grid)
            self.assertLess(a.residual,1e-9)
            self.assertLess(abs(a.at(p.reset)-regenerative_value(p,p.reset)),.006)
            self.assertLess(abs(a.boundary_high-regenerative_boundary(p)),.15)

    def test_advection_dominated_monotone_upwind(self):
        # A centered discretization would have a negative jump rate at n=129.
        p=Stop(.6,.08,.6,1.,0.,.3)
        coarse=solve_policy(p,Grid(-2.,5.,129))
        fine=solve_policy(p,Grid(-2.,5.,1025))
        err0=abs(coarse.at(.5)-regenerative_value(p,.5))
        err1=abs(fine.at(.5)-regenerative_value(p,.5))
        self.assertGreater(err0,.01)
        self.assertLess(err1,.0001)
        self.assertLess(err1,.1*err0)
        self.assertLess(fine.residual,1e-9)

    def test_invalid_domains_fail_closed(self):
        p=CASES[0]
        bad=(Grid(0.,5.,257),Grid(-10.,.5,257),Grid(-10.,6.,16),
             Grid(-10.,6.,True),Grid(float('nan'),6.,257),
             Grid(-10.,float('inf'),257),Grid(-10.,-3.,257))
        for g in bad:
            with self.subTest(g=g),self.assertRaises(ValueError):
                solve_policy(p,g)
        with self.assertRaises(TypeError):
            solve_policy(object(),Grid(-10.,6.,257))
        with self.assertRaises(ValueError):
            solve_value_iteration(p,Grid(-10.,6.,129),tolerance=0.)
        with self.assertRaises(ValueError):
            solve_policy(p,Grid(-10.,6.,129),decision_tolerance=-1.)
        with self.assertRaises(RuntimeError):
            solve_value_iteration(p,Grid(-10.,6.,129),max_iterations=1)
        with self.assertRaises(RuntimeError):
            solve_policy(p,Grid(-10.,6.,129),max_iterations=1)


if __name__=='__main__':
    unittest.main()
