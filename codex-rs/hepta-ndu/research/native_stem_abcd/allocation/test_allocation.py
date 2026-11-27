"""R9 actual quadrature, exact short-circuit and inherited-derivative checks."""
import unittest
from unittest.mock import patch
import numpy as np
import torch
from core import (training_rule, gate, fit, WidePolicy, SCALE, make_problem,
                  Graph, TARGET, qualifies, rule)

torch.set_num_threads(1)


class AllocationTests(unittest.TestCase):
    def test_quadrature_mass_and_equal_node_count(self):
        for name in ('cc5', 'gl5'):
            s, w = training_rule(name)
            self.assertEqual(s.shape, (625, 4))
            self.assertTrue((w > 0).all())
            self.assertAlmostEqual(w.sum(), 1.)
        self.assertFalse(np.array_equal(training_rule('cc5')[0], training_rule('gl5')[0]))

    def test_gaussian_monomials_through_degree_nine(self):
        s, w = training_rule('gl5')
        for j in range(4):
            for degree in range(10):
                expected = 0. if degree % 2 else SCALE[j]**degree/(degree+1)
                self.assertAlmostEqual(float(w @ s[:, j]**degree), expected, places=14)
        s, w = training_rule('cc5')
        self.assertGreater(abs(float(w @ (s[:, 2]/SCALE[2])**8)-1/9), 1e-4)

    def test_two_dimensional_gaussian_moment(self):
        s, w = training_rule('gl5')
        self.assertAlmostEqual(float(w @ ((s[:, 0]/SCALE[0])**4*(s[:, 2]/SCALE[2])**8)), 1/45, places=14)

    def test_short_circuit_matches_full_for_fixed_costs(self):
        vals = [TARGET-.002, TARGET-1e-6, TARGET, TARGET+1e-6]
        for c5 in vals:
            for c9 in vals:
                fn = lambda name: c5 if name == 'cc5' else c9
                self.assertEqual(gate(fn, 'full')[2], gate(fn, 'lazy')[2])

    def test_fine_evaluation_not_called_on_mathematical_failure(self):
        calls = []
        def f(name):
            calls.append(name)
            if name == 'cc9':
                raise AssertionError('unnecessary fine call')
            return TARGET+.1
        out = gate(f, 'lazy')
        self.assertEqual(calls, ['cc5'])
        self.assertEqual(out, (TARGET+.1, None, False))

    def test_no_skip_at_threshold_and_mismatched_fine_fails(self):
        calls = []
        def f(name):
            calls.append(name)
            return TARGET if name == 'cc5' else TARGET+.001
        self.assertFalse(gate(f, 'lazy')[2])
        self.assertEqual(calls, ['cc5', 'cc9'])

    def test_nonfinite_values_raise(self):
        for mode in ('full', 'lazy'):
            with self.assertRaises(FloatingPointError):
                gate(lambda name: float('nan'), mode)
            with self.assertRaises(FloatingPointError):
                gate(lambda name: TARGET if name == 'cc5' else float('inf'), mode)

    def test_gaussian_population_gradient_hvp(self):
        s, w = training_rule('gl5')
        policy = WidePolicy(64)
        # Full quadrature gradient; HVP on a normalized subset is a derivative test.
        t = torch.tensor(policy.initial, requires_grad=True)
        f, g = policy.adjoint(t, make_problem(), s, w)
        auto = torch.autograd.grad(f, t)[0]
        np.testing.assert_allclose(g.detach(), auto.detach(), atol=3e-13, rtol=1e-10)
        counts = dict(cache_hits=0, graphs=0, hvp=0, objectives=0)
        graph = Graph(policy, s[:20], w[:20]/w[:20].sum(), True, lambda: None, counts)
        v = np.random.default_rng(21).normal(size=len(t)); v /= np.linalg.norm(v)
        hv = graph.hvp(policy.initial, v)
        fd = (graph.jac(policy.initial+1e-5*v)-graph.jac(policy.initial-1e-5*v))/2e-5
        np.testing.assert_allclose(hv, fd, atol=2e-8, rtol=2e-5)

    def test_original_gate_not_redefined_for_gaussian_training(self):
        self.assertFalse(qualifies(.04, .0401))
        self.assertTrue(qualifies(TARGET, TARGET))

    def test_after_cap_does_not_qualify(self):
        with patch('core.evaluate', side_effect=lambda pol,z,p,s,chunk: np.zeros((len(s), 2))):
            theta, cp, info = fit(64, 11, 'adam', 'gl5', 'lazy', cap=1e-12)
        self.assertFalse(info['success'])
        self.assertIsNone(info['observed_wall'])
        self.assertTrue(info['checks'][-1]['terminal'])
        self.assertIsNotNone(info['checks'][-1]['cc9'])
        np.testing.assert_array_equal(theta, cp[-1])

    def test_initial_success_stops_with_exact_checkpoint(self):
        with patch('core.evaluate', side_effect=lambda pol,z,p,s,chunk: np.zeros((len(s), 2))):
            theta, cp, info = fit(64, 11, 'adjoint_ncg', 'gl5', 'lazy', cap=2)
        self.assertTrue(info['success'])
        self.assertEqual(info['counts']['updates'], 0)
        np.testing.assert_array_equal(theta, cp[0])

    def test_invalid_requests(self):
        with self.assertRaises(ValueError): training_rule('cc7')
        with self.assertRaises(ValueError): gate(lambda n: 0., 'guess')
        with self.assertRaises(ValueError): fit(64,11,'adam','gl5','lazy',float('nan'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
