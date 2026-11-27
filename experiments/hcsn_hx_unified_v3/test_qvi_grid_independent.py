"""Independent FD-QVI convergence/adversarial tests. Research-only, no admission."""

import math
import random
import unittest

from scipy.optimize import brentq

from .qvi_grid_independent import UnresolvedGrid, solve_regenerative_grid


def analytic_reference(mu, sigma, rho, cost, reset, tau, x):
    """One-dimensional smooth fit only for TESTS; not imported by the grid solver."""
    mag = math.hypot(mu, sigma*math.sqrt(2*rho))
    k = 2*rho/(mag+mu) if mu >= 0 else (mag-mu)/(sigma*sigma)
    d = math.exp(-rho*tau)
    def smooth(b):
        return k*(b-cost)+d*math.exp(-k*(b-reset))-1
    boundary = brentq(smooth,cost,cost+1/k,xtol=2e-14)
    cycle=d*math.exp(-k*(boundary-reset))
    amplitude=(boundary-cost)/(1-cycle)
    value=(amplitude*math.exp(-k*(boundary-x)) if x<boundary else
           x-cost+d*amplitude*math.exp(-k*(boundary-reset)))
    return boundary,value


class IndependentQviGridTests(unittest.TestCase):
    @staticmethod
    def solve(nodes=501, mu=.15, sigma=.9, rho=.12, tau=.4,
              lower=-17.0, upper=13.0):
        return solve_regenerative_grid(drift=mu,diffusion=sigma,
            discount=rho,cost=1.0,reset=-.6,refractory=tau,
            lower=lower,upper=upper,nodes=nodes)

    def test_independent_scalar_qvi_convergence_three_meshes(self):
        ref,_=analytic_reference(.15,.9,.12,1.,-.6,.4,0.)
        grids=[self.solve(nodes=n) for n in (301,601,1201)]
        errors=[abs(g.threshold-ref) for g in grids]
        print('QVI mesh threshold errors',errors)
        self.assertLess(errors[-1],.025)
        self.assertLess(errors[-1],errors[0])
        self.assertLess(errors[-1],errors[1])
        for x in (-3.,-.6,0.,1.,2.,3.5,6.):
            _,v=analytic_reference(.15,.9,.12,1.,-.6,.4,x)
            self.assertLess(abs(grids[-1].at(x)-v),.005)
        for g in grids:
            self.assertLess(g.bellman_residual,1e-8)
            self.assertTrue(all(not g.firing[i] for i in range(0,2)))
            self.assertTrue(all(g.firing[i] for i in range(g.nodes-2,g.nodes)))

    def test_drift_sign_refractory_and_boundary(self):
        for mu in (-.4,0.,.45):
            for tau in (0.,1.,3.):
                with self.subTest(drift=mu,refractory=tau):
                    g=self.solve(nodes=601,mu=mu,tau=tau)
                    b,_=analytic_reference(mu,.9,.12,1.,-.6,tau,0.)
                    self.assertLess(abs(g.threshold-b),.07)
                    self.assertLess(g.bellman_residual,1e-8)
                    for x in (-.6,0.,1.,4.):
                        _,val=analytic_reference(mu,.9,.12,1.,-.6,tau,x)
                        self.assertLess(abs(g.at(x)-val),.018)

    def test_causal_discounted_reset_and_refractory_monotonicity(self):
        a=self.solve(tau=0.)
        b=self.solve(tau=1.)
        c=self.solve(tau=3.)
        for x in (-.6,0.,1.,4.):
            self.assertGreaterEqual(a.at(x)+1e-10,b.at(x))
            self.assertGreaterEqual(b.at(x)+1e-10,c.at(x))
        self.assertLess(a.threshold,b.threshold)
        self.assertLess(b.threshold,c.threshold)

    def test_mesh_peclet_upwind_keeps_generator_positive(self):
        # Coarse grid and stiff drift force sign-safe upwinding.
        for mu in (-5.,5.):
            g=self.solve(nodes=61,mu=mu,rho=.2,lower=-12,upper=18)
            self.assertGreaterEqual(g.lower_rate,0)
            self.assertGreaterEqual(g.upper_rate,0)
            self.assertLess(g.bellman_residual,1e-8)

    def test_boundary_truncation_is_visible_not_certified(self):
        # The exact reference must not be used to auto-adjust the finite mesh.
        wide=self.solve(nodes=1001,lower=-22,upper=18)
        narrow=self.solve(nodes=751,lower=-17,upper=13)
        self.assertLess(abs(wide.threshold-narrow.threshold),.08)
        self.assertLess(abs(wide.at(0.)-narrow.at(0.)),.01)

    def test_seeded_64_regimes_independent_reference(self):
        # No generated sample is dropped from the stated accepted panel.
        rng=random.Random(20261031)
        largest_boundary=0.0
        largest_value=0.0
        for case in range(64):
            mu=rng.uniform(-.4,.4)
            sigma=rng.uniform(.6,1.4)
            rho=rng.uniform(.07,.3)
            tau=rng.uniform(0.,3.)
            reset=rng.uniform(-1.,-.1)
            with self.subTest(case=case):
                g=solve_regenerative_grid(drift=mu,diffusion=sigma,
                    discount=rho,cost=1.,reset=reset,refractory=tau,
                    lower=-26.,upper=21.,nodes=801)
                boundary,value=analytic_reference(mu,sigma,rho,1.,reset,tau,0.)
                largest_boundary=max(largest_boundary,abs(g.threshold-boundary))
                largest_value=max(largest_value,abs(g.at(0.)-value))
                self.assertLess(abs(g.threshold-boundary),.04)
                self.assertLess(abs(g.at(0.)-value),.003)
                self.assertLess(g.bellman_residual,1e-8)
        print('QVI seeded regimes',64,'worst boundary',largest_boundary,
              'worst V(0)',largest_value)

    def test_invalid_and_unresolved_cases_fail_closed(self):
        p=dict(drift=.1,diffusion=.9,discount=.1,cost=1.,reset=-.6,
               refractory=.4,lower=-12.,upper=12.,nodes=301)
        for changes in ({'diffusion':0.},{'discount':0.},{'reset':1.},
                        {'refractory':-.01},{'lower':-.6},{'upper':.2},
                        {'nodes':8},{'nodes':True},{'drift':float('nan')},
                        {'max_iterations':1},{'nodes':50000}):
            with self.subTest(changes=changes):
                with self.assertRaises(UnresolvedGrid):
                    solve_regenerative_grid(**(p|changes))
        g=solve_regenerative_grid(**p)
        for x in (g.lower-1.,g.upper+1.,float('nan')):
            with self.assertRaises(UnresolvedGrid):
                g.at(x)

if __name__ == '__main__':
    unittest.main()
