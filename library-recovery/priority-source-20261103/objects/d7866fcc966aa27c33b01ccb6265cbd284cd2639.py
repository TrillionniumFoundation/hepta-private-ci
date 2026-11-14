"""P0 bounded scalar regenerative QVI: independent numerical and adversarial tests."""
import math
import random
import unittest
from dataclasses import replace

import numpy as np
from scipy.special import lambertw

from .regenerative_qvi_oracle_v2 import (
    RegenerativeNeuron, UnresolvedQVI, independent_grid_oracle)


class RegenerativeQVIV2Tests(unittest.TestCase):
    @staticmethod
    def params():
        return RegenerativeNeuron(.13,.63,.2,1.4,-.2,.3)

    def test_closed_boundary_against_independent_lambert_w(self):
        rng=random.Random(2026103100)
        admitted=0
        refused=0
        for _ in range(120):
            p=RegenerativeNeuron(
                rng.uniform(-1,1),rng.uniform(.2,2),rng.uniform(.04,2),
                rng.uniform(.1,5),rng.uniform(-4,-.1),rng.uniform(0,2))
            try:
                s=p.solution
            except UnresolvedQVI:
                refused+=1
                continue  # explicit f64-domain refusal is not a successful check
            admitted+=1
            q0=math.exp(-p.discount*p.refractory-p.kappa*(p.cost-p.reset))
            z_ref=1+lambertw(-q0/math.e,k=0).real
            b_ref=p.cost+z_ref/p.kappa
            self.assertLess(abs(s.boundary-b_ref),2e-11*max(1,abs(b_ref)))
            self.assertGreater(s.boundary,p.cost)
            self.assertTrue(0<s.q<1)
            self.assertLess(abs(s.kappa*(s.boundary-p.cost)-(1-s.q)),1e-11)
        self.assertGreater(admitted,75)
        self.assertEqual(admitted+refused,120)

    def test_analytic_global_qvi_for_160_random_parameter_sets(self):
        rng=random.Random(2026103101)
        for _ in range(160):
            p=RegenerativeNeuron(rng.uniform(-.4,.5),rng.uniform(.3,1.5),
                    rng.uniform(.06,1.),rng.uniform(.5,3.),
                    rng.uniform(-3.,-.5),rng.uniform(0,1.))
            b=p.solution.boundary
            for offset in (-5,-2,-1,-.5,-1e-5,0,1e-5,.5,1,5):
                x=b+offset/p.kappa
                probe=p.qvi(x)
                self.assertLessEqual(probe.max_qvi_residual,1e-12)
                self.assertLessEqual(probe.generator_residual,1e-12)
                self.assertLessEqual(probe.obstacle_residual,1e-12)
                self.assertGreater(probe.value,0)
                self.assertEqual(probe.regime,'FIRE' if x>=b else 'CONTINUE')

    def test_matching_smooth_fit_and_local_derivatives(self):
        p=self.params();s=p.solution;b=s.boundary
        ref=p.qvi(b)
        self.assertAlmostEqual(ref.value,1/s.kappa,places=12)
        self.assertAlmostEqual(ref.immediate_fire_value,ref.value,places=12)
        h=1e-4
        left=(p.value(b-h)-p.value(b-2*h))/h
        right=(p.value(b+2*h)-p.value(b+h))/h
        self.assertLess(abs(left-1),2e-4)
        self.assertLess(abs(right-1),1e-10)
        self.assertLess(abs(p.qvi(b-h).obstacle_residual),h*h*s.kappa)

    def test_all_six_implicit_boundary_directions_against_centered_differences(self):
        rng=random.Random(2026103102)
        for _ in range(25):
            p=RegenerativeNeuron(rng.uniform(-.5,.5),rng.uniform(.4,1.2),
                rng.uniform(.1,.8),rng.uniform(.8,3.),rng.uniform(-2,-.5),
                rng.uniform(.2,.9))
            derivatives=p.boundary_sensitivities()
            for key,expected in derivatives.items():
                original=getattr(p,key)
                h=1e-5*max(1,abs(original))
                up=replace(p,**{key:original+h}).solution.boundary
                down=replace(p,**{key:original-h}).solution.boundary
                observed=(up-down)/(2*h)
                with self.subTest(key=key):
                    self.assertLess(abs(expected-observed)/max(1,abs(expected)),1e-7)

    def test_independent_grid_policy_iteration_convergence(self):
        p=self.params();s=p.solution
        xs=[s.boundary-.8/s.kappa,s.boundary-.1/s.kappa,s.boundary+.2/s.kappa]
        errs=[]
        for n in (65,129,257,513):
            g=independent_grid_oracle(p,n=n)
            self.assertLess(g.max_complementarity_residual,1e-9)
            self.assertLess(abs(g.grid_boundary-s.boundary),.25)
            errs.append(max(abs(np.interp(x,g.xs,g.values)-p.value(x)) for x in xs))
        self.assertTrue(all(errs[i+1]<errs[i] for i in range(3)),errs)
        self.assertLess(errs[-1],2e-4)

    def test_refractory_reduces_future_regeneration_value(self):
        p=self.params()
        short=replace(p,refractory=0)
        long=replace(p,refractory=2)
        self.assertLess(short.solution.boundary,long.solution.boundary)
        self.assertGreater(short.value(p.solution.boundary-1),long.value(p.solution.boundary-1))

    def test_invalid_inputs_fail_closed(self):
        p=self.params()
        invalid=(dict(sigma=0.),dict(discount=0.),dict(reset=2),
                 dict(refractory=-1.),dict(drift=float('nan')))
        for delta in invalid:
            with self.subTest(delta=delta),self.assertRaises(UnresolvedQVI):
                replace(p,**delta)
        with self.assertRaises(UnresolvedQVI):
            p.qvi(float('inf'))
        with self.assertRaises(UnresolvedQVI):
            independent_grid_oracle(p,n=64)

    def test_underresolved_root_and_float_exponent_refuse(self):
        p=RegenerativeNeuron(0.,1.,.5,1.,1.-1e-13,0.)
        # Very shallow boundary can cause a numerically ill-conditioned root.
        try:
            s=p.solution
            self.assertGreater(s.root,1e-10)
        except UnresolvedQVI:
            pass
        p=self.params()
        with self.assertRaises(UnresolvedQVI):
            p.value(p.solution.boundary-2000)


if __name__=='__main__':
    unittest.main()
