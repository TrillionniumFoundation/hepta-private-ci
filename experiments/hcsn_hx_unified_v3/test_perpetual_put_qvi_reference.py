"""Reproducible simplified GBM optimal-stopping reference tests."""
import dataclasses
import math
import unittest

import numpy as np

from .perpetual_put_qvi_reference import (
    GBMPut, ReferenceDomainError, independent_grid_qvi, quantized_side_f32,
)


class TestPerpetualPutQVI(unittest.TestCase):
    def setUp(self):
        self.p=GBMPut(.08,.02,.23,1.)

    def test_domain_fail_closed(self):
        for args in ((0.,.02,.23,1.),(.08,-.01,.23,1.),(.08,.02,0.,1.),
                     (.08,.02,.23,0.),(math.inf,.02,.23,1.),
                     (True,.02,.23,1.),(.08,.02,float('nan'),1.)):
            with self.subTest(args=args),self.assertRaises(ReferenceDomainError):
                GBMPut(*args)

    def test_negative_characteristic_root(self):
        p=self.p
        b=p.beta_minus
        lhs=.5*p.sigma**2*b*(b-1)+(p.rate-p.dividend)*b-p.rate
        self.assertLess(b,0)
        self.assertAlmostEqual(lhs,0,places=12)

    def test_value_and_smooth_pasting(self):
        p=self.p
        b=p.boundary
        self.assertTrue(0<b<p.strike)
        self.assertAlmostEqual(p.value(b),p.strike-b,places=13)
        h=2e-5*b
        approx_derivative=(p.value(b+h)-p.value(b-h))/(2*h)
        self.assertAlmostEqual(approx_derivative,-1.,delta=2e-5)

    def test_global_obstacle_and_generator_on_log_grid(self):
        for p in (self.p,GBMPut(.04,0,.6,1),GBMPut(.03,.25,.13,2),
                  GBMPut(.2,.01,.7,3)):
            for state in np.geomspace(p.boundary/1e3,p.strike*1e3,1501):
                gen,obstacle=p.qvi(float(state))
                tol=1e-12*max(p.strike,1.)
                self.assertLessEqual(gen,tol)
                self.assertLessEqual(obstacle,tol)
                self.assertAlmostEqual(max(gen,obstacle),0.,delta=tol)

    def test_global_stopping_generator_analytic_identity(self):
        p=self.p
        beta=p.beta_minus
        self.assertAlmostEqual(p.dividend*p.boundary-p.rate*p.strike,
                               .5*p.sigma**2*beta*p.strike,delta=1e-12)
        self.assertLess(p.dividend*p.boundary-p.rate*p.strike,0)

    def test_implicit_boundary_gradients(self):
        p=self.p
        for name,analytic in p.sensitivities().items():
            old=getattr(p,name)
            h=old*1e-5 if old else 1e-6
            plus=dataclasses.replace(p,**{name:old+h}).boundary
            minus=dataclasses.replace(p,**{name:old-h}).boundary
            finite_diff=(plus-minus)/(2*h)
            self.assertAlmostEqual(analytic,finite_diff,
                                   delta=3e-6*max(1.,abs(analytic)))

    def test_continuation_convexity(self):
        p=self.p
        b=p.boundary
        for v in np.geomspace(b*1.0001,p.strike*100,100):
            val=p.value(float(v))
            second=p.beta_minus*(p.beta_minus-1)*val/(v*v)
            self.assertGreater(second,0)
            self.assertGreater(val,max(p.strike-v,0.))

    def test_grid_policy_independent_value_convergence(self):
        p=self.p
        reports=[]
        for n in (129,257,513):
            solution=independent_grid_qvi(p,n=n)
            self.assertLess(solution.max_complementarity_residual,5e-8)
            err=abs(solution.active_boundary-p.boundary)
            value_err=max(abs(np.interp(v,solution.spots,solution.values)-p.value(v))
                          for v in (.45,.75,1.,1.5,2.))
            reports.append((err,value_err))
        self.assertLess(reports[-1][0],.035)
        self.assertLess(reports[-1][1],.002)
        # Value errors converge on this fixed five-spot benchmark.
        # The exercise does not prove a boundary convergence rate; finite
        # grid stop indices can stay constant across successive meshes.
        self.assertGreater(reports[0][1],reports[1][1])
        self.assertGreater(reports[1][1],reports[2][1])

    def test_fp32_alias_is_ambiguous(self):
        b=np.float32(.7)
        # Opposite true f64 sides that map to the same f32 representable value.
        b64=float(b)
        self.assertEqual(quantized_side_f32(math.nextafter(b64,0.),b64),'AMBIGUOUS')
        self.assertEqual(quantized_side_f32(math.nextafter(b64,math.inf),b64),'AMBIGUOUS')
        self.assertEqual(quantized_side_f32(b64*1.1,b64),'ABOVE')
        self.assertEqual(quantized_side_f32(b64*.9,b64),'BELOW')

    def test_quantized_invalid_inputs(self):
        for pair in ((0.,1.),(1.,0.),(float('nan'),1.),(float('inf'),1.),
                     (-1.,1.),(True,1.)):
            with self.assertRaises(ReferenceDomainError):
                quantized_side_f32(*pair)

    def test_refuse_underresolved_boundary(self):
        with self.assertRaises((ArithmeticError,OverflowError)):
            GBMPut(1e-300,0.,1e-300,1e-300).boundary


if __name__=='__main__':
    unittest.main()
