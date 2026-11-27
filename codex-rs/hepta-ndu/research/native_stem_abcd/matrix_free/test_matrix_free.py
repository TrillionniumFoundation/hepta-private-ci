"""Matrix-free derivatives, no dense fallback, budget and promotion conformance."""
import unittest
from unittest.mock import patch
import numpy as np
import torch
from solver import (Derivatives, Policy, adjoint, empty_counts, fit,
                    make_problem, rule)

torch.set_num_threads(1)


class MatrixFreeTests(unittest.TestCase):
    def setUp(self):
        self.policy = Policy('nonlinear', 11)
        self.p = make_problem()
        self.states, self.weights = rule('cc3')
        self.x = self.policy.initial.copy()
        self.rng = np.random.default_rng(7001)

    def engine(self, explicit=True):
        return Derivatives(self.policy, self.p, self.states, self.weights,
                           explicit, empty_counts(), lambda: None)

    def test_01_adjoint_gradient_matches_ad(self):
        a, b = self.engine(), self.engine(False)
        np.testing.assert_allclose(a.gradient(self.x), b.gradient(self.x),
                                   rtol=1e-10, atol=2e-13)

    def test_02_hvp_matches_dense_on_several_directions(self):
        e = self.engine()
        H = e.dense(self.x)
        for _ in range(3):
            v = self.rng.normal(size=78)
            np.testing.assert_allclose(e.hvp(self.x, v), H @ v, rtol=1e-10, atol=2e-12)

    def test_03_hvp_matches_centered_gradient_difference(self):
        e = self.engine()
        v = self.rng.normal(size=78); v /= np.linalg.norm(v)
        hp = e.hvp(self.x, v)
        d = (e.gradient(self.x+1e-5*v) - e.gradient(self.x-1e-5*v)) / 2e-5
        np.testing.assert_allclose(hp, d, rtol=1e-6, atol=3e-10)

    def test_04_hvp_matches_forward_jvp(self):
        e = self.engine()
        v = self.rng.normal(size=78)
        hp = torch.func.jvp(e.gradient_function, (torch.tensor(self.x),),
                            (torch.tensor(v),))[1].detach().numpy()
        np.testing.assert_allclose(e.hvp(self.x, v), hp, rtol=1e-10, atol=2e-12)

    def test_05_cached_ad_hvp_matches_explicit(self):
        a, b = self.engine(), self.engine(False)
        v = self.rng.normal(size=78)
        np.testing.assert_allclose(a.hvp(self.x,v), b.hvp(self.x,v), atol=2e-12)

    def test_06_symmetry_and_linearity(self):
        e = self.engine()
        v, w = self.rng.normal(size=(2,78))
        Hv, Hw = e.hvp(self.x,v), e.hvp(self.x,w)
        self.assertAlmostEqual(float(w@Hv), float(v@Hw), places=11)
        np.testing.assert_allclose(e.hvp(self.x,2*v-3*w),2*Hv-3*Hw,atol=2e-12)

    def test_07_graph_reused_but_not_after_parameter_change(self):
        e = self.engine()
        v = np.ones(78)
        e.gradient(self.x); e.hvp(self.x,v); e.hvp(self.x,2*v)
        self.assertEqual(e.counts['gradient_graphs'],1)
        e.hvp(self.x+.01,v)
        self.assertEqual(e.counts['gradient_graphs'],2)
        self.assertEqual(e.counts['full_hessians'],0)
        self.assertEqual(e.counts['forward_tangent_lanes'],0)

    def test_08_cache_owns_input_bytes(self):
        e = self.engine()
        x = self.x.copy(); e.gradient(x); x[0] += 1.
        self.assertFalse(np.array_equal(x,e.key))
        e.gradient(x)
        self.assertEqual(e.counts['gradient_graphs'],2)

    def test_09_cached_value_matches_new_scalar_evaluation(self):
        e = self.engine()
        v = e.value(self.x);e.gradient(self.x)
        self.assertAlmostEqual(v,e.value(self.x),places=14)

    def test_10_nonuniform_law_matters(self):
        e = self.engine();a=e.gradient(self.x)
        uniform = np.full(len(self.states),1/len(self.states))
        other = Derivatives(self.policy,self.p,self.states,uniform,True,empty_counts(),lambda:None)
        self.assertGreater(float(np.max(np.abs(a-other.gradient(self.x)))),1e-3)

    def test_11_fine_rule_hvp_agrees(self):
        s,w = rule('cc5');v=self.rng.normal(size=78)
        a = Derivatives(self.policy,self.p,s,w,True,empty_counts(),lambda:None)
        b = Derivatives(self.policy,self.p,s,w,False,empty_counts(),lambda:None)
        np.testing.assert_allclose(a.hvp(self.x,v),b.hvp(self.x,v),atol=5e-12)

    def test_12_ncg_never_calls_dense_and_reduces_training_objective(self):
        s,w=rule('cc3')
        start=float(self.policy.value(torch.tensor(self.x),self.p,s,w))
        with patch.object(Derivatives,'dense',side_effect=AssertionError('dense fallback')):
            z,r=fit(11,'adjoint_ncg','cc3',1.5)
        final=float(self.policy.value(torch.tensor(z),self.p,s,w))
        self.assertLess(final,start)
        self.assertGreater(r['counts']['hvp'],0)
        self.assertEqual(r['counts']['full_hessians'],0)

    def test_13_same_initial_weights_for_all_methods(self):
        a=Policy('nonlinear',23).initial;b=Policy('nonlinear',23).initial
        np.testing.assert_array_equal(a,b)
        self.assertEqual(a.size,78)

    def test_14_adaptive_promotes_without_holdout(self):
        z,r=fit(11,'adam','adaptive',1.5)
        self.assertEqual(r['final_rule'],'cc5')
        self.assertIsNotNone(r['promotion_reason'])
        self.assertEqual(r['stages'][0]['rule'],'cc3')
        self.assertTrue(np.isfinite(z).all())

    def test_15_invalid_inputs_fail(self):
        for args in [(11,'bad','cc5',1.),(11,'adam','cc9',1.),(11,'adam','cc5',0.)]:
            with self.assertRaises(ValueError):fit(*args)

    def test_16_untrained_control_preserves_bytes(self):
        z,r=fit(11,'none')
        np.testing.assert_array_equal(z,self.x)
        self.assertEqual(r['counts']['updates'],0)

    def test_17_fixed_cc5_has_no_promotion(self):
        z,r=fit(11,'ad_ncg','cc5',1.)
        self.assertEqual(r['promotion_checks'],[])
        self.assertEqual(r['final_rule'],'cc5')
        self.assertEqual(r['counts']['full_hessians'],0)


if __name__=='__main__':
    unittest.main(verbosity=2)
