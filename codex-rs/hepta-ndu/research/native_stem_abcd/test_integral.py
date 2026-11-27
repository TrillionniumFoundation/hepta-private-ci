"""R3 exact-primitive, differential, invariance and actual-fit tests."""
import unittest
from unittest.mock import patch

import numpy as np
import torch
from torch.func import jacfwd

from integral import IntegralStem, ScalarIntegralStem, fresh_terminals, representation_witness
from models import StateStem, assign, vector
from problem import decimal_oracle, make_world, terminals
from run import fit, predictions, residual
from structured import invariant_probe, new_terminals, panel_world


class IntegralTests(unittest.TestCase):
    def setUp(self):
        self.world = make_world()
        self.w = self.world.tensor()
        self.g = torch.tensor(terminals(self.world, 'train'), dtype=torch.float64)

    def test_identical_initialization_and_all_groups_learn(self):
        m, n = IntegralStem(23), IntegralStem(23)
        np.testing.assert_array_equal(vector(m), vector(n))
        self.assertEqual(vector(m).size, vector(StateStem()).size)
        residual(m, self.w, self.g, 3).square().sum().backward()
        for p in m.parameters():
            self.assertTrue(torch.isfinite(p.grad).all())
            self.assertGreater(float(p.grad.abs().sum()), 0)

    def test_exact_primitive_against_independent_segment_sum(self):
        m = IntegralStem()
        assign(m, np.random.default_rng(81).uniform(-2, 2, 65))
        p = self.w['p']
        grid = m.knots.numpy()
        q = m.knot_values(p).detach().numpy()
        u = np.random.default_rng(91).uniform(-7, 7, (15, len(p)))
        actual = m.primitive(torch.tensor(u), p).detach().numpy()
        expected = np.zeros_like(u)
        for i in range(len(u)):
            for j in range(len(p)):
                lo, hi = sorted([0, u[i, j]])
                cuts = np.unique(np.r_[lo, grid[(grid > lo) & (grid < hi)], hi])
                vals = np.interp(cuts, grid, q[j]) - float(p[j])
                area = sum((cuts[k+1]-cuts[k])*(vals[k]+vals[k+1])/2 for k in range(len(cuts)-1))
                expected[i,j] = area if u[i,j] >= 0 else -area
        np.testing.assert_allclose(actual, expected, atol=3e-14, rtol=1e-12)

    def test_derivative_is_interpolated_q_including_knots_and_tails(self):
        m = IntegralStem()
        assign(m, np.random.default_rng(19).uniform(-1, 1, 65))
        p = self.w['p']
        u = torch.tensor(np.tile(np.array([-7., -4., -0.125, 0., 0.125, 4., 7.])[:,None],(1,len(p))), requires_grad=True)
        derivative = torch.autograd.grad(m.primitive(u,p).sum(),u)[0] + p
        q = m.knot_values(p).detach().numpy()
        expected = np.array([[np.interp(v, m.knots, q[j]) for j,v in enumerate(row)] for row in u.detach().numpy()])
        np.testing.assert_allclose(derivative.detach(),expected,atol=2e-13,rtol=1e-12)

    def test_full_jacobian_and_chain_adjoint(self):
        m = IntegralStem(intervals=16)
        t = torch.tensor(vector(m),requires_grad=True)
        r = residual(m,self.w,self.g,2,t)
        j = jacfwd(lambda x: residual(m,self.w,self.g,2,x))(t.detach())
        grad = torch.autograd.grad(r.square().sum(),t)[0]
        np.testing.assert_allclose(grad.detach(),(2*j.T@r.detach()).detach(),atol=2e-12)
        for k in (0,7,33,64):
            e = torch.zeros_like(t); e[k]=1e-5
            fd=(residual(m,self.w,self.g,2,t+e)-residual(m,self.w,self.g,2,t-e))/(2e-5)
            np.testing.assert_allclose(j[:,k].detach(),fd.detach(),atol=1e-9,rtol=2e-4)

    def test_arbitrary_weights_preserve_structure(self):
        m=IntegralStem()
        for seed in (39,41,43):
            assign(m,np.random.default_rng(seed).uniform(-12,12,65))
            r=invariant_probe(m,self.world)
            for k,v in r.items():
                if k != 'numerical_probes_only':
                    self.assertLess(v,3e-13,k)

    def test_outcome_exchange_symmetry(self):
        m=IntegralStem()
        a,b,p=self.g[:,self.w['left']],self.g[:,self.w['right']],self.w['p']
        np.testing.assert_allclose(m.certainty(a,b,p,self.w['risk']).detach(),
                                  m.certainty(b,a,1-p,self.w['risk']).detach(),atol=2e-14)

    def test_probability_is_structural_before_training(self):
        world=panel_world(2,'joint'); g=fresh_terminals(world,'indicator')
        truth=g@np.linalg.matrix_power(world.kernel(),8).T
        for seed in (11,23,47):
            m=IntegralStem(seed);assign(m,np.random.default_rng(seed).uniform(-12,12,65))
            pred=predictions(m,'B',world.tensor(),g,8)[-1]
            np.testing.assert_allclose(pred,truth,atol=2e-14)
            self.assertGreaterEqual(pred.min(),0); self.assertLessEqual(pred.max(),1)

    def test_zero_tiny_risk_and_constants(self):
        m=IntegralStem();p=self.w['p'];a=self.g;b=-a
        mean=p*a+(1-p)*b
        for risk in (0.,1e-12):
            r=torch.full_like(p,risk)
            np.testing.assert_allclose(m.certainty(a,b,p,r).detach(),mean,atol=1e-11)
        for risk in (0.,1e-12,1.):
            r=torch.full_like(p,risk)
            np.testing.assert_allclose(m.certainty(a,a,p,r).detach(),a,atol=1e-14)

    def test_all_terminal_generators_are_fresh(self):
        prior={row.tobytes() for row in terminals(self.world,'train')}
        prior|={row.tobytes() for row in terminals(self.world,'transfer')}
        for f in ('uniform','composed','indicator'):
            old={row.tobytes() for row in new_terminals(self.world,f)}
            new={row.tobytes() for row in fresh_terminals(self.world,f)}
            # Indicator collision is meaningful and must not silently substitute a new draw.
            if f != 'indicator': self.assertFalse(new & (prior | old))
            self.assertGreaterEqual(len(new),30)

    def test_representation_witness_converges_without_extra_parameters(self):
        truth=decimal_oracle(self.world,self.g.numpy(),3)
        errors=[]
        for n in (16,32,64,128):
            m=representation_witness(n)
            errors.append(np.max(np.abs(predictions(m,'B',self.w,self.g.numpy(),3)-truth)))
            self.assertEqual(vector(m).size,65)
        for old,new in zip(errors,errors[1:]): self.assertLess(new,old/3)

    def test_first_step_witness_error_bound(self):
        m=representation_witness(64)
        a,b=self.g[:,self.w['left']],self.g[:,self.w['right']]
        truth=decimal_oracle(self.world,self.g.numpy(),1)[1]
        pred=m(self.g,self.w).detach().numpy()
        bound=self.world.discount*float((a-b).abs().max())*(np.sqrt(3)/18)*(8/64)**2/8
        self.assertLessEqual(float(np.max(np.abs(pred-truth))),bound+1e-13)

    def test_refinement_changes_no_trained_weight(self):
        m=IntegralStem();n=IntegralStem(intervals=128);assign(n,vector(m))
        np.testing.assert_array_equal(vector(m),vector(n))
        self.assertNotEqual(m.knots.numel(),n.knots.numel())

    def test_real_trf_updates_shared_weights_without_oracle(self):
        m=IntegralStem(intervals=16)
        before=float(residual(m,self.w,self.g,2).square().sum().detach())
        with patch('run.decimal_oracle',side_effect=AssertionError('oracle leakage')):
            r=fit(m,'C',self.w,self.g,2,3.0)
        after=float(residual(m,self.w,self.g,2).square().sum().detach())
        self.assertGreater(r['counts']['jacobian_evaluations'],0)
        self.assertLess(after,before)
        self.assertNotEqual(r['initial_weights_sha256'],r['final_weights_sha256'])

    def test_scalar_control_is_same_primitive_not_reference_call(self):
        m=ScalarIntegralStem();assign(m,np.array([1.]))
        n=representation_witness(64)
        np.testing.assert_allclose(m(self.g,self.w).detach(),n(self.g,self.w).detach(),atol=1e-14)
        self.assertEqual(vector(m).size,1)

    def test_scalar_initial_model_is_expectation(self):
        m=ScalarIntegralStem();p=self.w['p']
        target=self.w['c']+self.w['gamma']*(p*self.g[:,self.w['left']]+(1-p)*self.g[:,self.w['right']])
        np.testing.assert_allclose(m(self.g,self.w).detach(),target,atol=1e-14)

    def test_invalid_configuration_fails(self):
        for n in (-1,3,9,512,4.5):
            with self.assertRaises(ValueError): IntegralStem(intervals=n)
        with self.assertRaises(ValueError):fresh_terminals(self.world,'test-picked')


if __name__=='__main__': unittest.main(verbosity=2)
