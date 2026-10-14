"""Adversarial numerical and authority tests for action-gap stopping.

These are model-free mechanism tests, never pretrained efficacy receipts.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parent))
from decision import Task,Option,NotCertified,certify,cheap_and_fixed
from study import plan,verify_plan,predict,hexdigest,FROZEN_SOURCE_SHA
from independent_score import replay

class TestCertifiedDecision(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan=plan()
        cls.sealed=predict(cls.plan)

    def test_all_192_tasks_have_separate_source_groups(self):
        self.assertTrue(verify_plan(self.plan))
        self.assertEqual(hexdigest(self.plan),FROZEN_SOURCE_SHA)
        self.assertEqual(len({x['task_id'] for x in self.plan['cases']}),192)
        self.assertEqual(len(self.sealed['entries']),192)

    def test_complete_independent_two_window_replay(self):
        r=replay(self.plan,self.sealed)
        self.assertEqual(r['summary']['cohort_a']['count'],96)
        self.assertEqual(r['summary']['cohort_b']['count'],96)
        self.assertEqual(sum(x['certified'] for x in r['summary'].values()),192)
        self.assertFalse(r['physical_model_execution'])
        self.assertFalse(r['natural_world_reasoning_gain'])
        self.assertFalse(r['production_accepted'])
        self.assertEqual(r['authority'],'DENY_ALL')

    def test_interval_certifies_one_unambiguous_decision(self):
        c=self.plan['cases'][0]
        from study import from_row
        v=certify(from_row(c))
        self.assertTrue(v['certified_nominal'])
        self.assertGreater(v['positive_gap_lower_bound'],0)
        self.assertFalse(v['continuum_or_FP64_rigorous_certificate'])
        self.assertTrue(v['work_calls']>=3)

    def test_equal_best_actions_budget_exhausts_and_no_fake_winner(self):
        t=Task('tie',1.,.8,.3,.4,.2,4,(Option('a',.27,0.),Option('b',.27,0.)))
        v=certify(t,max_calls=8)
        self.assertIsNone(v['choice'])
        self.assertFalse(v['certified_nominal'])
        self.assertTrue(v['budget_exhausted'])
        self.assertEqual(v['work_calls'],8)

    def test_no_legal_action_cannot_infer_certificate(self):
        t=Task('stop',1.,.8,.3,.4,.2,4,(Option('abstain',0.,0.),Option('b',.27,0.)))
        with self.assertRaises(NotCertified):certify(t)

    def test_bad_task_units(self):
        for opts in ((Option('a',0.,-.1),Option('b',.2,0.)),
                     (Option('a',0.,0.),Option('a',.2,0.)),
                     (Option('a',float('nan'),0.),Option('b',.2,0.)),
                     (Option('a',0.,0.),)):
            with self.subTest(opts=opts),self.assertRaises(NotCertified):
                Task('v',.5,.8,.3,.4,.2,4,opts).validate()

    def test_work_budget(self):
        from study import from_row
        task=from_row(self.plan['cases'][0])
        for cap in (-1,0,1,2,201,True):
            with self.subTest(cap=cap),self.assertRaises(NotCertified):certify(task,max_calls=cap)

    def test_cheap_control_never_is_called_certified(self):
        from study import from_row
        c=cheap_and_fixed(from_row(self.plan['cases'][0]))
        self.assertEqual(c['cheap_one_map_calls'],3)
        self.assertEqual(c['fixed_depth_calls'],12)
        self.assertNotIn('certified_nominal',c)

    def test_source_tampering_rejected_even_if_rehashed(self):
        p=copy.deepcopy(self.plan)
        p['cases'][0]['x0']+=.1
        with self.assertRaises(ValueError):verify_plan(p)
        with self.assertRaises(ValueError):replay(p,self.sealed)

    def test_seed_mutation_rejected(self):
        p=copy.deepcopy(self.plan)
        p['configuration']['seed_a']+=1
        with self.assertRaises(ValueError):verify_plan(p)

    def test_bad_authority(self):
        p=copy.deepcopy(self.plan)
        p['production_accepted']=True
        with self.assertRaises(ValueError):replay(p,self.sealed)

    def reject_sealed(self,mutation):
        s=copy.deepcopy(self.sealed)
        mutation(s)
        with self.assertRaises((ValueError,KeyError,TypeError)):
            replay(self.plan,s)

    def test_missing_case(self):self.reject_sealed(lambda s:s['entries'].pop())
    def test_duplicate_row(self):self.reject_sealed(lambda s:s['entries'].__setitem__(1,s['entries'][0]))
    def test_wrong_source_digest(self):self.reject_sealed(lambda s:s.update(source_sha256='f'*64))
    def test_forged_approval(self):self.reject_sealed(lambda s:s.update(production_accepted=True))
    def test_change_first_y(self):self.reject_sealed(lambda s:s['entries'][0]['nominal_early']['per_action'][0]['y'].__setitem__(0,21.))
    def test_underreported_calls(self):self.reject_sealed(lambda s:s['entries'][0]['nominal_early']['per_action'][0].update(calls=1))
    def test_wrong_radius(self):self.reject_sealed(lambda s:s['entries'][0]['nominal_early']['per_action'][1].update(radius=0))
    def test_wrong_lower(self):self.reject_sealed(lambda s:s['entries'][0]['nominal_early']['per_action'][1].update(lower=777))
    def test_wrong_winner(self):self.reject_sealed(lambda s:s['entries'][0]['nominal_early'].update(choice='abstain'))
    def test_undercounted_operator_work(self):self.reject_sealed(lambda s:s['entries'][0]['nominal_early'].update(work_calls=1))
    def test_fake_uncertified(self):
        def mutate(s):
            e=s['entries'][0]['nominal_early']
            e.update(choice=None,certified_nominal=False,budget_exhausted=True,positive_gap_lower_bound=None)
        self.reject_sealed(mutate)
    def test_invalid_cheap_control(self):self.reject_sealed(lambda s:s['entries'][0]['controls'].update(fixed_depth_calls=0))
    def test_altered_cheap_action(self):
        def mutate(s):
            q=s['entries'][0]['controls']
            q['cheap_one_map']='control_1' if q['cheap_one_map']!='control_1' else 'control_2'
        self.reject_sealed(mutate)
    def test_altered_fixed_action(self):
        def mutate(s):
            q=s['entries'][0]['controls']
            q['fixed_depth']='control_1' if q['fixed_depth']!='control_1' else 'control_2'
        self.reject_sealed(mutate)
    def test_fake_negative_cpu(self):self.reject_sealed(lambda s:s['entries'][0]['nominal_early'].update(cpu_ns=-1))
    def test_missing_cheap_cpu(self):self.reject_sealed(lambda s:s['entries'][0]['controls'].update(cpu_ns=0))
    def test_wrong_stage(self):self.reject_sealed(lambda s:s.update(kind='source_plan'))

if __name__=='__main__':unittest.main()
