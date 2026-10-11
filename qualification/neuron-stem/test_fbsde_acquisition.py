"""Finite model proofs and adversarial checks; labels here are explicit fixtures."""
import math
import unittest
from itertools import product
from fbsde_acquisition import (JointKernel, Objective, ViewPort, certainty_equivalent,
                               exhaustive_reference, history_key, solve, terminal)


class AcquisitionTests(unittest.TestCase):
    def kernel(self):
        # Correlated observations, deliberately not a product of marginal evidence.
        return JointKernel.fit([(y, a, y, y) for y in range(2) for a in range(2)]*12,
                               2, {'source': 'test-only'}, .01)

    def test_sweep_matches_complete_policy_reference(self):
        kernel = self.kernel()
        for rho, cost, symbol in product((0., .5, 1.), (.01, .8), range(2)):
            obj = Objective(costs=(cost, cost), rho=rho); h = ((0, symbol),)
            a, b = solve(kernel, h, obj), exhaustive_reference(kernel, h, obj)
            self.assertAlmostEqual(a['value'], b['value'], places=12)
            self.assertEqual(a['action'], b['action'])
            self.assertEqual(b['policies_evaluated'], 9)

    def test_nonzero_risk_generator_and_complete_martingale(self):
        k = JointKernel.fit([(0, 0, 0, 0)]*8+[(1, 0, 1, 1)]*2, 2, {})
        r = solve(k, ((0, 0),), Objective(costs=(.01, .02), rho=.5))
        self.assertTrue(r['edges'])
        for e in r['edges']:
            self.assertLess(e['residual'], 1e-12)
            for y, z in zip(e['children'], e['z']):
                self.assertAlmostEqual(y, e['value']-e['generator']+z)
        self.assertTrue(any(abs(e['generator']) > 0 for e in r['edges']))

    def test_cash_additive_monotone_risk(self):
        q = [.2, .8]; values = [-1., 1.]
        self.assertLessEqual(certainty_equivalent(values, q, .5), certainty_equivalent(values, q, 0))
        self.assertAlmostEqual(certainty_equivalent([x-.2 for x in values], q, .5),
                               certainty_equivalent(values, q, .5)-.2)

    def test_incomplete_or_nonfinite_model_fails(self):
        for bad in ((0.,)*16, (1.,)*15, (float('nan'),)*16):
            with self.assertRaises(ValueError): JointKernel(bad, 2, 2, {})
        for rho in (-1, True, float('inf')):
            with self.assertRaises(ValueError): certainty_equivalent([0.], [1.], rho)

    def test_public_prefix_invariance(self):
        kernel = self.kernel(); obj = Objective()
        # Different future observations cannot change the same prefix's decision.
        root = [solve(kernel, ((0, 0),), obj)['action'] for _ in range(4)]
        self.assertEqual(len(set(root)), 1)
        with self.assertRaises(ValueError): history_key(((0, 0), (1, 0), (1, 1)), 2)
        with self.assertRaises(ValueError): history_key(((1, 0),), 2)

    def test_port_only_calls_requested_evidence(self):
        calls = []
        def fetch(view): calls.append(view); return view % 2, {'actual': view}
        port = ViewPort(fetch, 2)
        with self.assertRaises(ValueError): port.read(2)
        self.assertEqual(calls, [])
        self.assertEqual(port.read(0), ((0, 0),)); self.assertEqual(calls, [0])
        port.read(2); self.assertEqual(calls, [0, 2])
        with self.assertRaises(ValueError): port.read(2)

    def test_high_cost_selects_no_extra_evidence(self):
        result = solve(self.kernel(), ((0, 0),), Objective(costs=(1., 1.)))
        self.assertFalse(result['action'].startswith('read:'))

    def test_joint_not_marginal_independence(self):
        k = self.kernel()
        _, _, law = k.distribution(((0, 0), (1, 1)))
        self.assertGreater(law[2][1], .99)
        self.assertAlmostEqual(k.distribution(((0, 0),))[2][2][1], .5)

    def test_binding_changes_identity(self):
        k = self.kernel(); other = JointKernel(k.counts, 2, 2, {'source': 'different'})
        self.assertNotEqual(k.identity, other.identity)


if __name__ == '__main__': unittest.main()
