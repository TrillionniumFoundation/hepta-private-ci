"""Real equation, state-update, independent-reference and optimizer checks."""
import unittest
from unittest.mock import patch
import numpy as np
import torch
from torch.func import jacfwd
from problem import (MatrixStem,AttentionStem,make_problem,initial_states,initial_moments,
                     policy_value,objective,moment_gradient,stationarity,enumerate_policy,riccati,scalar_lower_bound)
from reference import dense_tree_reference
from solve import vector,assign,fit

torch.set_num_threads(1)


class PopulationTests(unittest.TestCase):
    def setUp(self): self.p=make_problem();self.model=MatrixStem()

    def test_same_initial_full_family(self):
        np.testing.assert_array_equal(vector(MatrixStem(23)),vector(MatrixStem(23)))
        self.assertEqual(len(vector(self.model)),108)

    def test_all_transition_groups_get_gradients(self):
        objective(self.model,self.p,initial_states()).backward()
        g=self.model.weights.grad.numpy()
        self.assertTrue(np.isfinite(g).all());self.assertTrue((np.linalg.norm(g,axis=(-1,-2))>1e-4).all())

    def test_optimization_changes_forward_representation(self):
        s=torch.tensor(initial_states());mode=torch.zeros(len(s),dtype=torch.long)
        before=self.model(s,mode,0).detach().clone()
        values=vector(self.model);values[4]+=.2;assign(self.model,values)
        self.assertGreater(float((before-self.model(s,mode,0)).abs().max().detach()),.1)

    def test_exact_moments_equal_entire_tree(self):
        cost=objective(self.model,self.p,initial_states()).detach()
        tree=enumerate_policy(self.model,self.p,initial_states())
        self.assertAlmostEqual(float(cost),float(tree['cost'].mean().detach()),places=12)
        mass=torch.zeros(len(initial_states())*2,dtype=torch.float64).scatter_add(0,tree['origin'],tree['prob'])
        np.testing.assert_allclose(mass,1.,atol=2e-15)

    def test_independent_population_adjoint_matches_autograd(self):
        gradient,moments=moment_gradient(self.model,self.p,initial_states())
        objective(self.model,self.p,initial_states()).backward()
        np.testing.assert_allclose(gradient.detach(),self.model.weights.grad,rtol=1e-11,atol=1e-12)
        self.assertGreater(float(torch.linalg.eigvalsh(moments).min().detach()),0.)

    def test_chain_gradient_matches_full_tree_gradient(self):
        small=initial_states()[:5]
        a=torch.autograd.grad(objective(self.model,self.p,small),self.model.weights)[0]
        b=torch.autograd.grad(enumerate_policy(self.model,self.p,small)['cost'].mean(),self.model.weights)[0]
        np.testing.assert_allclose(a,b,rtol=2e-11,atol=1e-12)

    def test_stationarity_jacobian_finite_differences(self):
        theta=torch.tensor(vector(self.model));shape=self.model.weights.shape
        fun=lambda t:stationarity(self.model,self.p,t.reshape(shape))
        j=jacfwd(fun)(theta)
        for i in (0,17,60,107):
            e=torch.zeros_like(theta);e[i]=1e-6
            np.testing.assert_allclose(j[:,i].detach(),((fun(theta+e)-fun(theta-e))/2e-6).detach(),rtol=3e-5,atol=1e-9)

    def test_riccati_is_stationary_positive_control_hessian(self):
        K,P,c,H=riccati(self.p)
        r=stationarity(self.model,self.p,torch.tensor(K))
        self.assertLess(float(r.abs().max()),1e-13)
        self.assertGreater(float(np.linalg.eigvalsh(H).min()),.1)

    def test_dense_scenario_QP_independently_matches(self):
        K,P,c,_=riccati(self.p)
        for mode in range(2):
            s=initial_states()[7+mode]
            ref=dense_tree_reference(self.p,s,mode)
            self.assertAlmostEqual(ref['cost'],float(s@P[mode]@s+c[mode]),places=11)
            np.testing.assert_allclose(ref['first_action'],K[0,mode]@s,atol=2e-12)
            self.assertLess(ref['kkt_residual'],1e-12)
            self.assertGreater(ref['minimum_hessian_eigenvalue'],0.)

    def test_scalar_impossibility_lower_bound_is_positive(self):
        result=scalar_lower_bound(self.p)
        self.assertGreater(result['objective_gap_lower_bound'],1e-12)
        scalar=MatrixStem(family='scalar');K,P,c,_=riccati(self.p)
        best=float((torch.tensor(P)*initial_moments(initial_states())).sum()+c.mean())
        observed=float(objective(scalar,self.p,initial_states()).detach())-best
        self.assertGreater(observed,result['objective_gap_lower_bound'])

    def test_matrices_are_genuinely_cross_coordinate(self):
        K,_,_,_=riccati(self.p)
        off=K.copy()
        for i in range(3):off[:,:,i,i]=0;off[:,:,i,i+3]=0
        self.assertGreater(float(np.linalg.norm(off)),.1)
        self.assertGreater(float(np.linalg.norm(self.p.target@self.p.F[:3,:3]-self.p.F[:3,:3]@self.p.target)),.05)

    def test_no_oracle_access_during_fit(self):
        old=vector(self.model)
        with patch('problem.riccati',side_effect=AssertionError('oracle in fit')):
            report=fit(self.model,self.p,'adjoint',3.)
        self.assertGreater(report['counts']['jacobian_calls'],0)
        self.assertFalse(np.array_equal(old,vector(self.model)))
        self.assertLess(float(stationarity(self.model,self.p,self.model.weights).abs().max().detach()),1e-5)

    def test_true_attention_receives_gradient(self):
        m=AttentionStem();v=enumerate_policy(m,self.p,initial_states()[:2])['cost'].mean();v.backward()
        self.assertGreater(float(m.attention.self_attn.in_proj_weight.grad.abs().sum()),0.)

    def test_scalar_and_diagonal_shapes(self):
        for family,count in [('scalar',6),('diagonal',36)]:
            m=MatrixStem(family=family)
            self.assertEqual(len(vector(m)),count);self.assertEqual(m.gains().shape,(3,2,3,6))
            self.assertTrue(torch.isfinite(objective(m,self.p,initial_states())))

    def test_new_state_law_is_not_training_rows(self):
        train={s.tobytes() for s in initial_states()}
        self.assertFalse(train & {s.tobytes() for s in initial_states('new')})

    def test_named_interventions_only(self):
        for name in ('dynamics','preference','noise'):
            new=make_problem(name)
            np.testing.assert_array_equal(new.target,self.p.target)
        with self.assertRaises(ValueError):make_problem('unknown')
        with self.assertRaises(ValueError):initial_states('oracle-picked')

    def test_forward_noise_is_not_dropped(self):
        K,_,c,_=riccati(self.p)
        self.assertGreater(float(c.min()),0)

    def test_finite_cap_validation(self):
        for cap in (-1,float('nan'),float('inf')):
            with self.assertRaises(ValueError):fit(self.model,self.p,'adam',cap)


if __name__=='__main__':unittest.main(verbosity=2)
