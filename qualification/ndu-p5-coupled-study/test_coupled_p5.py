"""Independent adversarial regression tests, including optimized Python mode."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from coupled_binary import Profile, Unsupported, defects, direct_uncontrolled, mapping, solve, transport
from independent_reference import direct_map, gaussian_solve, newton, prefixes
from study import audit, execute, prepare, h, create_only, load, verify_plan


class P5MathTests(unittest.TestCase):
    def test_prefix_breadth_first_matches_heap(self):
        self.assertEqual(prefixes(3), [(),(0,),(1,),(0,0),(0,1),(1,0),(1,1)])
    def test_exact_forward_noise_symmetry(self):
        p=Profile(steps=2,sigma=.3,a=0.,x0=.5)
        x=transport(p,[0.,0.,0.])
        self.assertAlmostEqual((x[1]+x[2])/2,.5)
        self.assertAlmostEqual(x[2]-x[1],2*.3*p.h**.5)
    def test_independent_public_information_recursion(self):
        for x in (-.6,0.,.7):
            p=Profile(steps=4,x0=x,a=.6)
            y=[.01*i for i in range(15)]
            for z,w in zip(mapping(p,y),direct_map(p,y)):
                self.assertAlmostEqual(z,w,places=13)
    def test_exact_conditional_covariance(self):
        p=Profile(steps=5,a=.4,sigma=.3)
        z=solve(p)
        d=z['defects']
        self.assertTrue(z['accepted_global_discrete'])
        self.assertLess(d['z_sigma_equals_b_residual'],1e-14)
        self.assertLess(d['local_bsde_residual'],2e-9)
        self.assertEqual(d['terminal_residual'],0.)
        self.assertFalse(d['float_roundoff_rigorously_enclosed'])
    def test_newton_picard_same_discrete_root(self):
        p=Profile(steps=4,a=.85,x0=-.6)
        s=solve(p);n=newton(p)
        self.assertLess(max(abs(x-y) for x,y in zip(s['y'],n['y'])),2e-9)
        self.assertGreater(n['operator_calls'],s['calls'])
    def test_direct_uncoupled_is_cheaper(self):
        p=Profile(steps=5,a=0.)
        direct=direct_uncontrolled(p);coupled=solve(p)
        self.assertEqual(direct['calls'],1)
        self.assertGreaterEqual(coupled['calls'],2)
        self.assertEqual(direct['y'],coupled['y'])
    def test_wrong_reset_has_zero_terminal_but_global_failure(self):
        p=Profile(steps=5,a=.6,x0=.7)
        wrong=solve(p,reset_depth=2)
        self.assertFalse(wrong['accepted_global_discrete'])
        self.assertEqual(wrong['defects']['terminal_residual'],0.)
        self.assertGreater(wrong['defects']['full_fixed_point_residual'],.05)
    def test_coupling_beyond_global_regularity_fails_pre_mesh(self):
        for k in (1,3,9):
            with self.subTest(steps=k),self.assertRaisesRegex(Unsupported,'contraction'):
                solve(Profile(steps=k,a=1.1))
    def test_underbudget_fails(self):
        with self.assertRaisesRegex(Unsupported,'iteration exhausted'):
            solve(Profile(steps=5,a=.6),max_calls=1)
    def test_illformed_profiles_fail(self):
        for kwargs in ({'steps':0},{'horizon':0.},{'x0':float('nan')},
                       {'a':-1.},{'sigma':float('inf')},{'steps':10}):
            with self.subTest(kwargs=kwargs),self.assertRaises(Unsupported):
                solve(replace(Profile(),**kwargs))
    def test_unbounded_wrong_reset_rejected(self):
        for d in (-1,0,4,2.5):
            with self.subTest(depth=d),self.assertRaises(Unsupported):
                solve(Profile(steps=4),reset_depth=d)
    def test_reference_jacobian_singular_fails(self):
        with self.assertRaisesRegex(ValueError,'singular'):
            gaussian_solve([[0.,0.],[0.,0.]],[1.,2.])
    def test_no_false_continuous_certification(self):
        s=solve(Profile())
        self.assertFalse(s['defects']['continuous_time_error_certified'])
        self.assertFalse(s['production_accepted'])
        self.assertEqual(s['authority'],'DENY_ALL')


class FrozenStudyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan=prepare()
        cls.observed=execute(cls.plan)
        cls.replay=audit(cls.plan,cls.observed)

    def tamper(self,modifier):
        obs=deepcopy(self.observed)
        modifier(obs)
        with self.assertRaises(ValueError): audit(self.plan,obs)

    def test_full_sweep_admitted_and_failures_retained(self):
        result=self.replay
        self.assertEqual(result['total_predeclared_profiles'],60)
        self.assertEqual(result['executed_admitted_profiles'],48)
        self.assertEqual(result['unsupported_global_regular_domain'],12)
        self.assertEqual(result['independent_newton_comparisons'],36)
        self.assertLess(result['max_root_difference_newton_picard'],2e-9)
        self.assertGreater(result['max_wrong_reset_global_residual'],.1)
        self.assertEqual(result['total_cheaper_direct_uncontrolled_operator_calls'],12)
        self.assertFalse(result['p5_accepted'])
    def test_plan_provenance_drift(self):
        plan=deepcopy(self.plan)
        plan['profiles'][0]['a']=.99
        with self.assertRaises(ValueError): verify_plan(plan)
    def test_incomplete_slot(self): self.tamper(lambda x: x['rows'].pop())
    def test_reordered_slot(self): self.tamper(lambda x: x['rows'].reverse())
    def test_fake_source_digest(self): self.tamper(lambda x: x.update(code_sha256={'bad':'1'}))
    def test_fabricated_global_acceptance(self):
        self.tamper(lambda x:x['rows'][0]['wrong_reset'].update(accepted_global_discrete=True))
    def test_missing_global_replay(self):
        self.tamper(lambda x:x['rows'][1]['picard']['y'].__setitem__(0,3.))
    def test_counter_fabrication(self):
        self.tamper(lambda x:x['rows'][1]['picard'].update(calls=1))
    def test_fake_newton_improvement(self):
        self.tamper(lambda x:x['rows'][0]['newton'].update(operator_calls=1))
    def test_wrong_reset_covert_edit(self):
        self.tamper(lambda x:x['rows'][0]['wrong_reset']['y'].__setitem__(0,10.))
    def test_synthetic_qualifications_cannot_promote(self):
        self.tamper(lambda x:x.update(production_accepted=True))
    def test_nonfinite_or_missing_cpu(self):
        self.tamper(lambda x:x['rows'][0]['picard'].update(cpu_ns=0))
    def test_numeric_z_tamper(self):
        self.tamper(lambda x:x['rows'][1]['picard']['defects'].update(z_sigma_equals_b_residual=.01))
    def test_failed_regular_domain_must_remain_failed(self):
        self.tamper(lambda x:x['rows'][-1].update(status='completed'))
    def test_create_only_outputs(self):
        with TemporaryDirectory() as d:
            p=Path(d)/'frozen.json'
            create_only(p,self.plan)
            self.assertEqual(load(p),self.plan)
            with self.assertRaises(FileExistsError):create_only(p,self.plan)
    def test_json_serialization_no_future_outcomes(self):
        self.assertTrue(self.plan['no_prehorizon_future_labels'])
        self.assertFalse(self.observed['pretrained_model_execution'])
        self.assertTrue(self.replay['numerical_discrete_qualification_only'])
        self.assertFalse(self.replay['natural_task_reasoning_gain'])

if __name__=='__main__':unittest.main()
