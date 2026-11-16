"""New-model tests: independent FP64 values/state and genuine derivatives."""

import math
import unittest

import numpy as np
import torch

from qualification.hcsn_regenerative import process as scalar
from qualification.hcsn_regenerative.audit import five_point_derivative
from qualification.hcsn_regenerative.tensor import (
    TensorDiffusion, TensorReset, finite_horizon_value, regenerative_transition,
)


def tensor(value, dtype=torch.float64, requires_grad=False):
    return torch.tensor(value,dtype=dtype,requires_grad=requires_grad)


class TensorRegenerationTests(unittest.TestCase):
    def setUp(self):
        self.reset = TensorReset(.25,.11,.7)
        self.process = TensorDiffusion(tensor(-.1),tensor(.3),tensor(.15))
        self.oracle = scalar.KilledDiffusion(-.1,.3,.15)
        self.oracle_reset = scalar.ResetRule(.25,.11,.7)

    def test_value_and_occupation_match_independent_scalar_reference(self):
        for x,t in ((.35,1.4),(.02,.4),(1.2,.1),(.4,2.1)):
            actual = finite_horizon_value(self.process,self.reset,x,t,active_reward=.3,terminal_reward=.2)
            expected = scalar.finite_horizon_value(self.oracle,self.oracle_reset,x,t,active_reward=.3,terminal_reward=.2)
            for name in ('single_cycle','regenerative','expected_discounted_hits','active_probability','active_time'):
                self.assertAlmostEqual(float(getattr(actual,name)),getattr(expected,name),places=10,msg=name)

    def test_fp32_is_a_real_fp32_graph(self):
        x = tensor(.35,torch.float32,True)
        parameters = [tensor(v,torch.float32,True) for v in (-.1,.3,.15)]
        process = TensorDiffusion(*parameters)
        value = finite_horizon_value(process,self.reset,x,1.4,active_reward=.3,terminal_reward=.2)
        expected = scalar.finite_horizon_value(self.oracle,self.oracle_reset,.35,1.4,active_reward=.3,terminal_reward=.2)
        self.assertEqual(value.regenerative.dtype,torch.float32)
        self.assertLess(abs(float(value.regenerative.detach())-expected.regenerative),2e-5)
        gradients = torch.autograd.grad(value.regenerative,[x]+parameters)
        self.assertTrue(all(bool(torch.isfinite(g)) for g in gradients))

    def test_value_gradients_against_independent_reference(self):
        values = [.35,1.4,-.1,.3,.15]
        inputs = [tensor(v,requires_grad=True) for v in values]
        def evaluate(v):
            return scalar.finite_horizon_value(scalar.KilledDiffusion(*v[2:]),self.oracle_reset,
                                               v[0],v[1],active_reward=.3,terminal_reward=.2).regenerative
        result = finite_horizon_value(TensorDiffusion(*inputs[2:]),self.reset,*inputs[:2],active_reward=.3,terminal_reward=.2)
        gradients = torch.autograd.grad(result.regenerative,inputs)
        for i,gradient in enumerate(gradients):
            h=2e-5
            plus,minus = values.copy(),values.copy()
            plus[i]+=h
            minus[i]-=h
            expected=(evaluate(plus)-evaluate(minus))/(2*h)
            self.assertLess(abs(float(gradient)-expected),2e-7,msg=str(i))

    def test_log_boundary_derivative_uses_same_margin(self):
        log_value,log_boundary=tensor(.4,requires_grad=True),tensor(.05,requires_grad=True)
        value=finite_horizon_value(self.process,self.reset,log_value-log_boundary,1.4).regenerative
        derivatives=torch.autograd.grad(value,(log_value,log_boundary))
        self.assertAlmostEqual(float(derivatives[0]+derivatives[1]),0.,places=13)

    def test_killed_state_and_explicit_upper_tail(self):
        edges=[0.,.2,.5,1.,2.]
        actual=self.process.transition(.35,1.4,edges)
        expected=self.oracle.transition(.35,1.4,edges)
        np.testing.assert_allclose(actual.survivor_bins.numpy(),expected.survivor_bins,atol=2e-12)
        self.assertAlmostEqual(float(actual.upper_tail),expected.upper_tail,places=12)
        self.assertAlmostEqual(float(actual.hit+actual.upper_tail+actual.survivor_bins.sum()),1.,places=12)
        unbounded=self.process.transition(.35,1.4,[0.,.2,math.inf])
        self.assertEqual(float(unbounded.upper_tail),0.)
        self.assertAlmostEqual(float(unbounded.survivor_bins.sum()+unbounded.hit),1.,places=12)

    def test_regenerative_state_matches_reference(self):
        edges=[0.,.2,.5,1.,2.]
        actual=regenerative_transition(self.process,self.reset,.35,1.4,edges,quadrature_order=128,
                                       refractory_edges=[0.,.04,.11])
        expected=scalar.regenerative_transition(self.oracle,self.oracle_reset,.35,1.4,edges,
                                                refractory_edges=[0.,.04,.11])
        np.testing.assert_allclose(actual.active_bins.numpy(),expected.active_bins,atol=2e-8)
        np.testing.assert_allclose(actual.refractory_bins.numpy(),expected.refractory_bins,atol=2e-10)
        self.assertLess(abs(float(actual.mass_residual)),2e-8)
        self.assertLess(float(actual.quadrature_error),2e-8)

    def test_initial_boundary_and_release_atoms(self):
        for t in (0.,.05,.11,.17):
            actual=finite_horizon_value(self.process,self.reset,0.,t,active_reward=.3,terminal_reward=.2)
            expected=scalar.finite_horizon_value(self.oracle,self.oracle_reset,0.,t,active_reward=.3,terminal_reward=.2)
            self.assertAlmostEqual(float(actual.regenerative),expected.regenerative,places=10)
        before=regenerative_transition(self.process,self.reset,0.,.05,[0.,.2,.5,math.inf])
        at=regenerative_transition(self.process,self.reset,0.,.11,[0.,.2,.5,math.inf])
        self.assertEqual(float(before.refractory_bins.sum()),1.)
        np.testing.assert_array_equal(at.active_bins.numpy(),[0.,1.,0.])
        self.assertEqual(float(at.refractory_bins.sum()),0.)

    def test_zero_time_has_unrenormalized_dirac(self):
        actual=self.process.transition(.2,0.,[0.,.2,.5])
        np.testing.assert_array_equal(actual.survivor_bins.numpy(),[0.,1.])
        self.assertEqual(float(actual.hit),0.)
        self.assertEqual(float(actual.upper_tail),0.)

    def test_batched_cells_preserve_parameter_gradients(self):
        mu=tensor([-.1,.1],requires_grad=True)
        x=tensor([.35,.5],requires_grad=True)
        process=TensorDiffusion(mu,tensor([.3,.4]),tensor(.15))
        value=finite_horizon_value(process,self.reset,x,tensor([1.4,.8]))
        gradients=torch.autograd.grad(value.regenerative.sum(),(mu,x))
        self.assertEqual(tuple(value.regenerative.shape),(2,))
        self.assertTrue(all(bool(torch.isfinite(g).all()) for g in gradients))
        state=regenerative_transition(process,self.reset,x,tensor([1.4,.8]),[0.,.2,.5,1.,2.],quadrature_order=128)
        self.assertEqual(tuple(state.active_bins.shape),(2,4))

    def test_declared_parameter_and_numerical_domains_reject(self):
        for mu,sigma,q in ((2.1,.3,.15),(-.1,.049,.15),(-.1,.3,0.)):
            with self.assertRaises(ValueError):
                TensorDiffusion(tensor(mu),tensor(sigma),tensor(q))
        with self.assertRaises(ValueError):
            finite_horizon_value(self.process,self.reset,.35,1.4,max_terms=1)
        with self.assertRaises(ValueError):
            TensorReset(.2,0.)
        with self.assertRaises(ValueError):
            TensorReset(tensor(.2,requires_grad=True),.1)
        with self.assertRaises(ValueError):
            self.process.transition(.2,.3,tensor([0.,.2,.5],requires_grad=True))
        with self.assertRaises(ValueError):
            self.process.hit_probability(tensor(0.,requires_grad=True),.3)
        with self.assertRaises(ValueError):
            self.process.hit_probability(.2,tensor(0.,requires_grad=True))

    def test_repeated_events_are_not_endpoint_probability(self):
        value=finite_horizon_value(self.process,TensorReset(.08,.04),.05,3.,max_terms=100)
        self.assertGreater(float(value.expected_discounted_hits),1.)
        self.assertLess(float(self.process.hit_probability(.05,3.)),1.)
        self.assertGreater(float(value.regenerative),float(value.single_cycle))

    def test_remaining_horizon_is_not_restarted(self):
        at_boundary=finite_horizon_value(self.process,self.reset,0.,.8).regenerative
        restarted=finite_horizon_value(self.process,self.reset,self.reset.margin,.8-self.reset.refractory).regenerative
        self.assertAlmostEqual(float(at_boundary),self.reset.hit_reward+math.exp(-.15*.11)*float(restarted),places=11)

    def test_fp32_small_discount_strong_drift_value_and_occupation(self):
        reset = TensorReset(.25, .11)
        for mu, q in ((-2., .01), (-1.8, .0105), (1.8, .0105)):
            process = TensorDiffusion(*(tensor(v, torch.float32) for v in (mu, .05, q)))
            actual = finite_horizon_value(process, reset, .35, 1.4,
                                          active_reward=.4, terminal_reward=.2)
            expected = scalar.finite_horizon_value(scalar.KilledDiffusion(mu, .05, q),
                                                  scalar.ResetRule(.25, .11), .35, 1.4,
                                                  active_reward=.4, terminal_reward=.2)
            self.assertEqual(actual.regenerative.dtype, torch.float32)
            for field in ("single_cycle", "regenerative", "expected_discounted_hits", "active_time"):
                self.assertLess(abs(float(getattr(actual, field))-getattr(expected, field)),
                                3e-4, msg=f"{mu=}, {q=}, {field=}")

    def test_fp32_small_discount_gradient_against_independent_reference(self):
        # q is strictly inside the declared domain; differences stay inside it.
        q = tensor(.0105, torch.float32, True)
        process = TensorDiffusion(tensor(-1.8, torch.float32), tensor(.05, torch.float32), q)
        actual = finite_horizon_value(process, TensorReset(.25, .11), .35, 1.4,
                                      active_reward=.4, terminal_reward=.2)
        gradient = torch.autograd.grad(actual.regenerative, q)[0]
        def reference(discount):
            return scalar.finite_horizon_value(scalar.KilledDiffusion(-1.8, .05, discount),
                                               scalar.ResetRule(.25, .11), .35, 1.4,
                                               active_reward=.4, terminal_reward=.2).regenerative
        full = five_point_derivative(reference, .0105, 1e-5)
        half = five_point_derivative(reference, .0105, 5e-6)
        self.assertLess(abs(full-half), 1e-6)
        self.assertTrue(bool(torch.isfinite(gradient)))
        self.assertLess(abs(float(gradient)-half), 3e-3+3e-3*abs(half))

    def test_atom_state_or_time_derivatives_are_rejected(self):
        # Release time has a terminal-payoff jump. Exact zero-time bin atoms
        # also have no qualified state derivative, even away from bin edges.
        for x, horizon in ((tensor(0.), tensor(.11, requires_grad=True)),
                           (tensor(.2, requires_grad=True), tensor(0.))):
            with self.assertRaises(ValueError):
                finite_horizon_value(self.process, self.reset, x, horizon, terminal_reward=.2)
            with self.assertRaises(ValueError):
                regenerative_transition(self.process, self.reset, x, horizon, [0., .2, .5])

    def test_fixed_atom_still_allows_generator_parameter_derivatives(self):
        parameters = [tensor(v, requires_grad=True) for v in (-.1, .3, .15)]
        process = TensorDiffusion(*parameters)
        actual = finite_horizon_value(process, self.reset, 0., .17,
                                      active_reward=.4, terminal_reward=.2)
        derivatives = torch.autograd.grad(actual.regenerative, parameters)
        self.assertTrue(all(bool(torch.isfinite(g)) for g in derivatives))

    def test_unresolved_finite_input_scale_rejects_before_nan_gradient(self):
        process = TensorDiffusion(*(tensor(v, torch.float32) for v in (-.1, .3, .15)))
        with self.assertRaises(FloatingPointError):
            process.hit_probability(tensor(1e30, torch.float32, True), 1.4)


if __name__=='__main__':
    unittest.main()
