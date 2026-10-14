"""R8 mechanism/derivative tests, not efficacy or independent quality observations."""
import unittest
from unittest.mock import patch
import numpy as np
import torch
from wide import WidePolicy, rule, make_problem
from engine import Graph, qualifies, fit, TARGET
from domain import Policy, adjoint

torch.set_num_threads(1)


class ScalingTests(unittest.TestCase):
    def setUp(self):
        self.p = make_problem(); self.s, self.w = rule('cc3')
        self.counts = dict(cache_hits=0, graphs=0, hvp=0, objectives=0)

    def test_width_four_matches_parent_values_and_gradient(self):
        a = WidePolicy(4, 23); b = Policy('nonlinear', 23)
        np.testing.assert_array_equal(a.initial, b.initial)
        t = torch.tensor(a.initial)
        np.testing.assert_array_equal(a.tree(t, self.p, self.s)[0], b.tree(t, self.p, self.s)[0])
        f, g = a.adjoint(t, self.p, self.s, self.w)
        ff, gg = adjoint(t, self.p, self.s, self.w)
        np.testing.assert_allclose(f, ff, atol=1e-14)
        np.testing.assert_allclose(g, gg, atol=1e-14)

    def test_parameter_counts_and_same_initial_bytes(self):
        for width, n in ((4,78),(16,162),(64,498),(256,1842)):
            a, b = WidePolicy(width, 47), WidePolicy(width, 47)
            self.assertEqual(len(a.initial), n)
            np.testing.assert_array_equal(a.initial, b.initial)

    def test_every_width_explicit_gradient_matches_ad(self):
        for width in (4,16,64,256):
            policy = WidePolicy(width)
            t = torch.tensor(policy.initial, requires_grad=True)
            f, g = policy.adjoint(t, self.p, self.s, self.w)
            other = torch.autograd.grad(f, t)[0]
            np.testing.assert_allclose(g.detach(), other.detach(), atol=2e-13, rtol=1e-10)
            groups = policy.unpack(g)
            for group in groups:
                self.assertGreater(float(group.detach().abs().sum()), 0)

    def test_hvp_all_widths_matches_finite_difference(self):
        for width in (4,16,64,256):
            policy = WidePolicy(width); x = policy.initial
            engine = Graph(policy, self.s, self.w, True, lambda:None, self.counts)
            v = np.random.default_rng(27).normal(size=len(x)); v /= np.linalg.norm(v)
            hv = engine.hvp(x, v)
            fd = (engine.jac(x+1e-5*v)-engine.jac(x-1e-5*v))/2e-5
            np.testing.assert_allclose(hv, fd, atol=1e-8, rtol=1e-5)

    def test_hvp_explicit_matches_ad_and_dense_small_width(self):
        policy = WidePolicy(4); x = policy.initial
        a = Graph(policy, self.s, self.w, True, lambda:None, self.counts)
        b = Graph(policy, self.s, self.w, False, lambda:None, self.counts)
        v = np.random.default_rng(88).normal(size=len(x))
        dense = torch.func.hessian(lambda z: policy.value(z,self.p,self.s,self.w))(torch.tensor(x))
        np.testing.assert_allclose(a.hvp(x,v), b.hvp(x,v), atol=2e-12)
        np.testing.assert_allclose(a.hvp(x,v), dense.numpy()@v, atol=2e-12)

    def test_cache_invalidation_after_parameter_change(self):
        policy = WidePolicy(4); x = policy.initial
        a = Graph(policy, self.s, self.w, True, lambda:None, self.counts)
        a.jac(x); a.hvp(x, np.ones_like(x))
        self.assertEqual(self.counts['graphs'], 1)
        a.jac(x+.01)
        self.assertEqual(self.counts['graphs'], 2)

    def test_no_dense_fallback_for_large_width(self):
        policy = WidePolicy(256); x=policy.initial
        a = Graph(policy, self.s, self.w, True, lambda:None, self.counts)
        with patch('torch.func.hessian',side_effect=AssertionError('dense fallback')), \
             patch('torch.func.jacfwd',side_effect=AssertionError('dense fallback')):
            self.assertEqual(a.hvp(x,np.ones_like(x)).shape,x.shape)

    def test_gate_requires_quality_and_integration_and_finite(self):
        self.assertTrue(qualifies(TARGET, TARGET))
        self.assertFalse(qualifies(TARGET+.0001,TARGET))
        self.assertFalse(qualifies(.04,.041))
        self.assertFalse(qualifies(float('nan'),.04))

    def test_initial_success_has_saved_checkpoint_no_updates(self):
        with patch('engine.evaluate',side_effect=lambda pol,z,p,s,chunk:np.zeros((len(s),2))):
            theta, cp, info = fit(4,11,'adjoint_ncg',cap=3.)
        self.assertTrue(info['success']); self.assertEqual(info['counts']['updates'],0)
        np.testing.assert_array_equal(cp[0],theta)
        self.assertGreater(info['monitor_wall'],0)

    def test_after_deadline_is_not_a_success(self):
        with patch('engine.evaluate',side_effect=lambda pol,z,p,s,chunk:np.zeros((len(s),2))):
            _, _, info = fit(4,11,'adam',cap=1e-10)
        self.assertFalse(info['success']); self.assertIsNone(info['observed_wall'])
        self.assertTrue(info['checks'][-1]['predicate'])
        self.assertFalse(info['checks'][-1]['within_cap'])

    def test_bounded_actions_and_quadrature_mass(self):
        pol = WidePolicy(256)
        _, levels, _, _, _ = pol.tree(torch.tensor(pol.initial)*10,self.p,self.s)
        self.assertAlmostEqual(self.w.sum(),1.)
        for L in levels:
            self.assertLessEqual(float(L['u'].abs().max()),self.p.bound)

    def test_invalid_requests(self):
        with self.assertRaises(ValueError): WidePolicy(5)
        with self.assertRaises(ValueError): fit(4,11,'unknown')


if __name__=='__main__': unittest.main(verbosity=2)
