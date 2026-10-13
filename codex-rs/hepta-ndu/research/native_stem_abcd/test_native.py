"""Executable mechanism/math checks; none of these tests is efficacy evidence."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import torch
from torch.func import jacfwd

from models import StateStem, TransformerStem, vector, assign, call_vector
from problem import (World, make_world, terminals, exact_step, decimal_oracle,
                     bernoulli_fbsde_defect)
from run import residual, fit, predictions, scores, write_json, digest


class NativeStemTests(unittest.TestCase):
    def setUp(self):
        self.world = make_world()
        self.w = self.world.tensor()
        self.g = torch.tensor(terminals(self.world, 'train'), dtype=torch.float64)

    def test_complete_forward_probability_mass(self):
        p = self.world.kernel()
        mu = np.ones(self.world.size)/self.world.size
        for _ in range(16):
            mu = mu@p
            self.assertAlmostEqual(mu.sum(), 1)
            self.assertTrue(np.all(mu >= 0))

    def test_experience_updates_preferences(self):
        for i in range(self.world.size):
            pref = i % 3
            self.assertEqual(self.world.left[i] % 3, max(0,pref-1))
            self.assertEqual(self.world.right[i] % 3, min(2,pref+1))

    def test_b_c_exact_same_initial_family(self):
        b, c = StateStem(47), StateStem(47)
        np.testing.assert_array_equal(vector(b),vector(c))
        np.testing.assert_array_equal(b(self.g,self.w).detach(), c(self.g,self.w).detach())

    def test_weight_roundtrip_changes_actual_computation(self):
        model = StateStem()
        old = model(self.g,self.w).detach().clone()
        weights = vector(model)
        weights[-1] += .13
        assign(model,weights)
        np.testing.assert_allclose(model(self.g,self.w).detach()-old,.13,atol=1e-14)
        np.testing.assert_array_equal(vector(model),weights)

    def test_functional_weight_path(self):
        m = StateStem()
        np.testing.assert_allclose(m(self.g,self.w).detach(),
                                   call_vector(m,torch.tensor(vector(m)),self.g,self.w).detach(),atol=0)

    def test_all_stem_weights_receive_population_gradients(self):
        m = StateStem()
        residual(m,self.w,self.g,3).square().sum().backward()
        for p in m.parameters():
            self.assertIsNotNone(p.grad)
            self.assertGreater(float(p.grad.abs().sum()),0)

    def test_transformer_is_real_trainable_attention(self):
        m = TransformerStem()
        residual(m,self.w,self.g,2).square().sum().backward()
        self.assertGreater(float(m.block.self_attn.in_proj_weight.grad.abs().sum()),0)
        self.assertGreater(float(m.embed.weight.grad.abs().sum()),0)

    def test_c_full_jacobian_vs_finite_difference(self):
        m = StateStem()
        t = torch.tensor(vector(m))
        j = jacfwd(lambda z:residual(m,self.w,self.g,2,z))(t).detach().numpy()
        for k in (0,7,33,64):
            e = torch.zeros_like(t)
            e[k] = 1e-6
            fd = (residual(m,self.w,self.g,2,t+e)-residual(m,self.w,self.g,2,t-e)).detach().numpy()/2e-6
            np.testing.assert_allclose(j[:,k],fd,rtol=2e-5,atol=2e-9)

    def test_adjoint_chain_gradient_vs_jacobian(self):
        m = StateStem()
        t = torch.tensor(vector(m),requires_grad=True)
        r = residual(m,self.w,self.g,3,t)
        grad = torch.autograd.grad(r.square().sum(),t)[0]
        j = jacfwd(lambda z:residual(m,self.w,self.g,3,z))(t.detach())
        np.testing.assert_allclose(grad.detach(),(2*j.T@r.detach()).detach(),rtol=1e-10,atol=1e-12)

    def test_wrong_frozen_target_gradient_is_not_used(self):
        m = StateStem()
        t = torch.tensor(vector(m),requires_grad=True)
        true = torch.autograd.grad(residual(m,self.w,self.g,2,t).square().sum(),t)[0]
        v, errors = self.g, []
        for _ in range(2):
            nxt = call_vector(m,t,v,self.w)
            errors.append((nxt-exact_step(v,self.w).detach()).flatten())
            v = nxt
        wrong = torch.autograd.grad(torch.cat(errors).square().mean(),t)[0]
        self.assertGreater(float((true-wrong).abs().max()),1e-5)

    def test_independent_decimal_matches_structured(self):
        pred = predictions(None,'D',self.w,self.g.numpy(),8)
        truth = decimal_oracle(self.world,self.g.numpy(),8)
        np.testing.assert_allclose(pred,truth,atol=3e-15,rtol=1e-14)

    def test_zero_risk_probability_matches_matrix_power(self):
        w = make_world(probability_profile=True)
        g = terminals(w,'probability')
        direct = predictions(None,'D',w.tensor(),g,5)[-1]
        np.testing.assert_allclose(direct,g@np.linalg.matrix_power(w.kernel(),5).T,atol=1e-14)

    def test_martingale_representation_nonidentity_covariance(self):
        self.assertLess(float(bernoulli_fbsde_defect(self.g,self.w).abs().max()),1e-14)
        a,b,p = self.g[:,self.w['left']],self.g[:,self.w['right']],self.w['p']
        z = a-b
        mean = p*a+(1-p)*b
        cross = p*(a-mean)*(1-p)+(1-p)*(b-mean)*(-p)
        np.testing.assert_allclose(cross,z*p*(1-p),atol=1e-14)

    def test_structured_monotonicity(self):
        add = torch.arange(self.g.numel()).reshape(self.g.shape)/self.g.numel()
        self.assertTrue(torch.all(exact_step(self.g+add,self.w)>=exact_step(self.g,self.w)))

    def test_structured_sup_contraction(self):
        other = self.g.flip(0)+.1
        err = (exact_step(other,self.w)-exact_step(self.g,self.w)).abs().max()
        self.assertLessEqual(float(err),self.world.discount*float((other-self.g).abs().max())+1e-14)

    def test_error_envelope_covers_entire_enumerated_domain(self):
        pred = predictions(StateStem(),'B',self.w,self.g.numpy(),8)
        truth = decimal_oracle(self.world,self.g.numpy(),8)
        self.assertTrue(scores(pred,truth,self.world)['envelope_verified'])

    def test_bounds_do_not_turn_training_residual_into_uniform_proof(self):
        truth = decimal_oracle(self.world,self.g.numpy(),3)
        fake = truth.copy()
        fake[-1,0,0] += .4
        result = scores(fake,truth,self.world)
        self.assertGreater(result['max_equation_defect'],.39)
        self.assertGreater(result['final_max_error'],.39)

    def test_transfer_tasks_disjoint(self):
        train = {digest(x.tobytes()) for x in terminals(self.world,'train')}
        test = {digest(x.tobytes()) for x in terminals(self.world,'transfer')}
        self.assertFalse(train & test)

    def test_unknown_split_refused(self):
        with self.assertRaises(ValueError):
            terminals(self.world,'test_alias')

    def test_probability_clipping_is_explicit(self):
        w = make_world(probability_profile=True)
        g = terminals(w,'probability')
        truth = decimal_oracle(w,g,1)
        pred = truth.copy()
        pred[-1,0,0]=1.5
        out=scores(pred,truth,w,True)
        self.assertGreater(out['probability_invalid_fraction'],0)
        self.assertGreater(out['raw_excess_brier'],out['clipped_excess_brier'])

    def test_changed_world_is_not_identical_kernel(self):
        self.assertFalse(np.array_equal(self.world.kernel(),make_world(changed=True).kernel()))

    def test_dimension_transfer_reuses_weights(self):
        m=StateStem()
        old=vector(m)
        large=make_world(bits=6)
        out=predictions(m,'B',large.tensor(),terminals(large,'transfer'),3)
        self.assertEqual(out.shape,(4,8,192))
        np.testing.assert_array_equal(old,vector(m))

    def test_terminal_boundary_exact_and_horizon_zero(self):
        out=predictions(StateStem(),'B',self.w,self.g.numpy(),0)
        np.testing.assert_array_equal(out[0],self.g.numpy())

    def test_invalid_kernel_rejected(self):
        for key,value in [('probability',np.zeros(12)),('risk',-np.ones(12)),('left',np.full(12,99))]:
            args={name:getattr(self.world,name) for name in ('bits','left','right','probability','cost','risk','discount')}
            args[key]=value
            with self.assertRaises(ValueError):
                World(**args)

    def test_readonly_kernel(self):
        with self.assertRaises(ValueError):
            self.world.probability[0]=.99

    def test_create_only_outputs(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'evidence.json'
            write_json(path,{'old':1})
            before=path.read_bytes()
            with self.assertRaises(FileExistsError):
                write_json(path,{'new':2})
            self.assertEqual(before,path.read_bytes())

    def test_actual_c_solve_without_oracle(self):
        m=StateStem()
        before=float(residual(m,self.w,self.g,2).square().sum().detach())
        with patch('run.decimal_oracle',side_effect=AssertionError('oracle leaked')):
            report=fit(m,'C',self.w,self.g,2,2.0)
        after=float(residual(m,self.w,self.g,2).square().sum().detach())
        self.assertLess(after,before)
        self.assertGreater(report['counts']['jacobian_evaluations'],0)
        self.assertNotEqual(report['initial_weights_sha256'],report['final_weights_sha256'])

    def test_actual_b_uses_same_population_residual(self):
        m=StateStem()
        before=float(residual(m,self.w,self.g,2).square().sum().detach())
        with patch('run.decimal_oracle',side_effect=AssertionError('oracle leaked')):
            report=fit(m,'B',self.w,self.g,2,1.0)
        after=float(residual(m,self.w,self.g,2).square().sum().detach())
        self.assertLess(after,before)
        self.assertGreater(report['counts']['optimizer_updates'],0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
