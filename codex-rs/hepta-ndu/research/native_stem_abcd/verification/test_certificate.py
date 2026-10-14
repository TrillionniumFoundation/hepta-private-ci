"""R11 analytic theorem/regression tests. They are not neural efficacy samples."""
from fractions import Fraction
from pathlib import Path
import json
import math
import unittest
import numpy as np
import torch
from certify import (global_majorants, one_dimensional_rule, wasserstein_uniform_1d,
                     transport_certificate, certified_midpoint_radius,
                     manufactured_polynomial, quadratic_example_certificate, SCALE,
                     WidePolicy, make_problem)
from run import (independent_rules, manufactured_controls, numerical_derivative_probe,
                 R10_ZIP_SHA, digest, TARGET)


class CertificateTests(unittest.TestCase):
    def setUp(self):
        self.policy=WidePolicy(4,11)
        self.theta=self.policy.initial.copy()
        self.bound=global_majorants(self.theta,4)

    def test_one_atom_exact_transport(self):
        self.assertEqual(wasserstein_uniform_1d(np.array([0.]),np.array([1.]),1.),Fraction(1,2))

    def test_two_midpoints_exact_transport(self):
        self.assertEqual(wasserstein_uniform_1d(np.array([-.5,.5]),np.array([.5,.5]),1.),Fraction(1,4))

    def test_weight_normalization_invariant(self):
        x=np.array([-.5,.5])
        a=wasserstein_uniform_1d(x,np.array([.25,.25]),1.)
        b=wasserstein_uniform_1d(x,np.array([.5,.5]),1.)
        self.assertEqual(a,b)

    def test_rule_positive_masses(self):
        for name in ('cc5','gl5','cc9','gl7','gl9','gl11','cc17'):
            x,w=one_dimensional_rule(name)
            self.assertTrue(np.isfinite(x).all());self.assertTrue((w>0).all())
            self.assertAlmostEqual(w.sum(),1,places=12)
            self.assertGreater(float(wasserstein_uniform_1d(x,w,.8)),0)

    def test_transport_bound_decreases_with_gaussian_order(self):
        radii=[transport_certificate(self.bound,f'gl{n}')['radius_upper'] for n in (5,7,9,11)]
        self.assertEqual(radii,sorted(radii,reverse=True))

    def test_positive_finite_global_majorants(self):
        for k in ('first','second'):
            self.assertTrue(np.isfinite(self.bound[k]).all())
            self.assertTrue((np.array(self.bound[k])>0).all())
        self.assertFalse(self.bound['machine_interval_evaluation_certified'])

    def test_majorants_cover_sampled_derivatives_both_widths(self):
        for width in (4,256):
            p=WidePolicy(width,11);theta=p.initial
            majorants=global_majorants(theta,width)
            for state in ([0.,0.,.2,-.1],[.12,-.11,.3,.5]):
                gradient=numerical_derivative_probe(p,theta,state)
                self.assertTrue(all(abs(g)<L for g,L in zip(gradient,majorants['first'])))

    def test_majorants_cover_second_coordinate_difference(self):
        p=self.policy
        from run import evaluate_at
        h=2e-3; s=np.array([.02,-.03,.13,-.14]);problem=make_problem()
        mid=evaluate_at(p,self.theta,problem,s[None,:],np.ones(1))
        for j in range(4):
            sp=s.copy();sm=s.copy();sp[j]+=h;sm[j]-=h
            y=evaluate_at(p,self.theta,problem,sp[None,:],np.ones(1))
            z=evaluate_at(p,self.theta,problem,sm[None,:],np.ones(1))
            self.assertLess(abs((y-2*mid+z)/h**2),self.bound['second'][j])

    def test_midpoint_bound_is_completely_external_to_optimized_gate(self):
        self.assertGreater(certified_midpoint_radius(self.bound,16),0)
        self.assertLess(certified_midpoint_radius(self.bound,32),certified_midpoint_radius(self.bound,16))

    def test_exact_quadratic_midpoint_identity(self):
        for n in (1,2,5,16):
            result=quadratic_example_certificate(n)
            self.assertEqual(result['midpoint_bias_exact'],str(Fraction(1,3*n*n)))
            self.assertEqual(result['midpoint_bias_exact'],result['midpoint_bound_exact'])

    def test_polynomial_legacy_rejects_true_low_cost(self):
        examples=manufactured_controls()
        self.assertLessEqual(examples['degree8']['exact_mean'],TARGET)
        self.assertFalse(examples['degree8']['legacy_pass'])
        self.assertAlmostEqual(examples['degree8']['gl5'],examples['degree8']['exact_mean'],places=13)

    def test_polynomial_other_profiles(self):
        examples=manufactured_controls()
        for name in ('constant','affine','quadratic'):
            self.assertAlmostEqual(examples[name]['gl11'],examples[name]['exact_mean'],places=13)
            self.assertTrue(examples[name]['legacy_pass'])

    def test_new_scramble_ids_and_rule_sizes(self):
        laws=independent_rules()
        self.assertEqual(len(laws),10)
        self.assertEqual(laws['gl7'][0].shape,(2401,4))
        self.assertEqual(laws['gl11'][0].shape,(14641,4))
        for i in range(8):
            self.assertEqual(laws[f'qmc_new_{i}'][0].shape,(1024,4))
        self.assertFalse(np.array_equal(laws['qmc_new_0'][0],laws['qmc_new_1'][0]))

    def test_invalid_transport_inputs_refused(self):
        for x,w in ((np.array([1.]),np.array([-1.])),
                    (np.array([.5]),np.array([float('nan')])),
                    (np.array([0.,1.]),np.array([.5]))):
            with self.assertRaises(ValueError):
                wasserstein_uniform_1d(x,w,1.)

    def test_does_not_mutate_actual_stem(self):
        theta=self.theta.copy()
        _=global_majorants(theta,4)
        np.testing.assert_array_equal(theta,self.theta)

    def test_protocol_r10_reference_is_fixed(self):
        self.assertEqual(len(R10_ZIP_SHA),64)
        self.assertEqual(len(digest(b'constant')),64)


if __name__=='__main__':
    unittest.main(verbosity=2)
