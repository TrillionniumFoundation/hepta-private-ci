"""Constructed controls and actual pinned-source regressions; no silent skips."""
from __future__ import annotations
import contextlib
import copy
import io
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from belief import Planner, aggregate, check_history, preference
from review import audit, rational_plan
from study import config, fit_prior, fold_indices, lifecycle, matched_slope, packet, read_training, run, setup, training_only
from material_news import encode, loads, prepare


def scenario(**kw):
    return {'name':'constructed','horizon':1,'step_fee':'1/1000','calibration_fee':'0','budget':128}|kw


class ModelTests(unittest.TestCase):
    def test_01_delayed_gain_nonmyopic(self):
        curves=((8,8,8,16),);s=scenario();p=Planner(curves,s)
        self.assertEqual(p.decision(())['action'],'continue')
        self.assertEqual(p.decision((4,4))['action'],'continue')
        self.assertEqual(matched_slope((4,4),s)['action'],'stop')
        self.assertAlmostEqual(p.decision(())['value'],float(rational_plan(curves,tuple(s.items()),'neutral')[0]),places=12)
    def test_02_no_gain_no_initial_pilot(self):
        self.assertEqual(Planner(((8,8,8,8),),scenario()).decision(())['action'],'stop')
    def test_03_expensive_pilot_rejected(self):
        self.assertEqual(Planner(((0,16,16,16),),scenario(step_fee='1')).decision(())['action'],'stop')
    def test_04_budget_seven(self):
        p=Planner(((0,16,16,16),),scenario(budget=7))
        self.assertEqual(p.decision(())['reason'],'hard_budget');self.assertEqual(p.solve.cache_info().currsize,1)
    def test_05_posterior_changes_after_observation(self):
        p=Planner(((4,2,2,2),(4,14,14,14)),scenario())
        self.assertGreater(p.posterior((8,))[1],p.posterior(())[1]);self.assertLess(p.posterior((0,))[1],p.posterior(())[1])
    def test_06_rational_values_all_profiles(self):
        curves=((4,5,8,15),(4,9,10,9));s=scenario(budget=32)
        for mode in ('neutral','fixed','ndu'):
            for history in ((),(0,),(4,),(8,)):
                p=Planner(curves,s,mode).decision(history);q=rational_plan(curves,tuple(s.items()),mode,history)
                self.assertAlmostEqual(p['value'],float(q[0]),places=11);self.assertEqual(p['to_step'],q[4])
    def test_07_future_observation_not_required(self):
        self.assertEqual(Planner(((3,12,14,14),),scenario()).decision(())['selected_steps'],0)
    def test_08_invalid_history(self):
        for h in ([1],(True,),(9,),(0,0,17),(0,0,0,0)):
            with self.subTest(h=h),self.assertRaises(ValueError):check_history(h)
    def test_09_invalid_prior(self):
        for curves in ((),((1,2,3),),((1,2,3,True),),((1,2,3,17),)):
            with self.assertRaises(ValueError):Planner(curves,scenario())
    def test_10_invalid_scenario(self):
        for s in (scenario(budget=True),scenario(budget=-1),scenario(horizon=0),scenario(step_fee='-1'),scenario(extra='x')):
            with self.assertRaises(ValueError):Planner(((1,2,3,4),),s)
    def test_11_preference_responds_only_to_observed_counts(self):
        self.assertEqual(str(preference((),'ndu')),'1/4');self.assertEqual(str(preference((0,),'ndu')),'3/8')
        self.assertEqual(str(preference((8,),'ndu')),'1/8');self.assertEqual(str(preference((0,0,0),'ndu')),'1/2')
    def test_12_translation_and_normalization(self):
        self.assertAlmostEqual(aggregate((.25,.75),(3.,4.),.25)-aggregate((.25,.75),(0.,1.),.25),3.)
        with self.assertRaises(ValueError):aggregate((.5,),(.5,),.25)
    def test_13_impossible_budget_history(self):
        with self.assertRaises(ValueError):Planner(((1,2,3,4),),scenario(budget=7)).decision((1,))
    def test_14_stop_has_sunk_cost_removed(self):
        p=Planner(((4,14,14,14),),scenario(step_fee='1')).decision((8,))
        self.assertGreater(p['stop_value'],0);self.assertEqual(p['action'],'stop')


    def test_33_admissible_prune_equivalence(self):
        for curves in (((8,8,8,16),),((4,12,14,14),(4,8,9,9))):
            for mode in ('neutral','fixed','ndu'):
                for s in (scenario(),scenario(step_fee='1')):
                    a=Planner(curves,s,mode,True).decision(())
                    b=Planner(curves,s,mode,False).decision(())
                    self.assertEqual(a['action'],b['action']);self.assertEqual(a['to_step'],b['to_step'])
                    self.assertAlmostEqual(a['value'],b['value'],places=11)
    def test_34_prune_avoids_expensive_tree(self):
        curves=((0,16,16,16),);s=scenario(step_fee='1')
        a=Planner(curves,s,pruning=True).decision(())
        b=Planner(curves,s,pruning=False).decision(())
        self.assertTrue(a['pruned']);self.assertEqual(a['evaluated_model_nodes'],1)
        self.assertGreater(b['evaluated_model_nodes'],1000)


class OriginalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name)
        cls.archive=Path(os.environ['NEWS_ARCHIVE']);cls.material=cls.root/'material'
        prepare(cls.archive,cls.material);cls.training=cls.root/'train.npz';training_only(cls.material,cls.training)
        cls.prior_path=cls.root/'prior.json'
        with contextlib.redirect_stdout(io.StringIO()):cls.prior=fit_prior(cls.training,cls.prior_path)
        cls.a,_=packet(cls.material/'worker.npz');_,_,cls.x=setup(cls.a);cls.run_path=cls.root/'run'
        with contextlib.redirect_stdout(io.StringIO()):run(cls.material,cls.prior_path,cls.run_path)
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def test_15_train_only_material(self):
        x,y,ids=read_training(self.training);self.assertEqual(x.shape,(64,384));self.assertEqual(len(y),64)
        with np.load(self.training,allow_pickle=False) as z:self.assertEqual(set(z.files),{'x','y','ids'})
    def test_16_prior_leak_field_rejected(self):
        x,y,ids=read_training(self.training);p=self.root/'leak.npz';np.savez(p,x=x,y=y,ids=ids,y_holdout=np.zeros(32))
        with self.assertRaises(ValueError):read_training(p)
    def test_17_fold_partition(self):
        self.assertEqual(sorted(sum(fold_indices(self.a['train_ids']),[])),list(range(64)))
        for r in self.prior['rows']:
            self.assertEqual(len(r['train_ids']),48);self.assertEqual(len(r['valid_ids']),16)
            self.assertFalse(set(r['train_ids'])&set(r['valid_ids']))
    def test_18_real_prior_cost_census(self):
        self.assertEqual(sum(r['actual_updates'] for r in self.prior['rows']),512)
        self.assertEqual(sum(r['validation_calls'] for r in self.prior['rows']),16)
        self.assertTrue(any(np.any(np.array(r['checkpoints']['8'])!=0) for r in self.prior['rows']))
    def test_19_no_cal_or_test_read_by_prior(self):
        with patch('study.packet',side_effect=AssertionError('prior read calibration')):
            with contextlib.redirect_stdout(io.StringIO()):p=fit_prior(self.training,self.root/'prior-only-repeat.json')
        self.assertEqual(p['curves'],self.prior['curves'])
    def test_20_budget_refusal_no_gradient(self):
        s=next(s for s in config()['scenarios'] if s['name']=='budget7')
        with patch('study.Trainer.step',side_effect=AssertionError('unaffordable gradient')):
            r=lifecycle(self.a,self.x,self.prior,'belief_ndu',s,lambda e:None)
        self.assertEqual(r['actual_steps'],0);self.assertEqual(r['calibration_calls'],0)
    def test_21_failure_no_seal(self):
        target=self.root/'failed-run'
        with patch('study.Trainer.step',side_effect=RuntimeError('injected training failure')):
            with self.assertRaises(RuntimeError):run(self.material,self.prior_path,target)
        self.assertFalse((target/'sealed.json').exists());self.assertIn(b'failure',(target/'journal.jsonl').read_bytes())
    def test_22_full_original_audit(self):
        with contextlib.redirect_stdout(io.StringIO()):r=audit(self.archive,self.material,self.training,self.prior_path,self.run_path,self.root/'audit.json')
        self.assertEqual(r['verified_lifecycles'],84);self.assertFalse(r['ndu_superiority_established'])
        self.assertFalse(r['reliable_future_roi_established']);self.assertTrue(r['cold_start_cost_not_amortized_by_hypothetical_horizon'])
    def rejected(self,mutator):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);run_copy=root/'run';shutil.copytree(self.run_path,run_copy)
            prior=copy.deepcopy(self.prior);seal=loads((run_copy/'sealed.json').read_bytes());mutator(prior,seal)
            (root/'prior.json').write_bytes(encode(prior));(run_copy/'sealed.json').write_bytes(encode(seal))
            with self.assertRaises(ValueError):audit(self.archive,self.material,self.training,root/'prior.json',run_copy,root/'audit.json')
    def test_23_prior_tamper(self):self.rejected(lambda p,s:p['curves'][0].__setitem__(1,16))
    def test_24_missing_lifecycle(self):self.rejected(lambda p,s:s['rows'].pop())
    def test_25_duplicate_lifecycle(self):self.rejected(lambda p,s:s['rows'].append(s['rows'][0]))
    def test_26_false_authority(self):self.rejected(lambda p,s:s.update(posture='PRODUCTION'))
    def test_27_false_encoder_calls(self):self.rejected(lambda p,s:s.update(fresh_encoder_calls=1))
    def test_28_future_head_injection(self):
        self.rejected(lambda p,s:s['rows'][0]['checkpoints'].update({'128':p['rows'][0]['checkpoints']['128']}))
    def test_29_output_no_overwrite(self):
        original=(self.run_path/'sealed.json').read_bytes()
        with self.assertRaises(FileExistsError):run(self.material,self.prior_path,self.run_path)
        self.assertEqual((self.run_path/'sealed.json').read_bytes(),original)
    def test_30_decisions_before_training(self):
        for r in loads((self.run_path/'sealed.json').read_bytes())['rows']:
            for i,e in enumerate(r['events']):
                if e['kind']=='train_start':
                    self.assertEqual(r['events'][i-1]['kind'],'decision');self.assertEqual(r['events'][i-1]['to_step'],e['to_step'])
    def test_31_disjoint_paid_calibration(self):
        for r in loads((self.run_path/'sealed.json').read_bytes())['rows']:
            ids=r['calibration_ids'];self.assertEqual(len(ids),len(set(ids)))
            self.assertFalse(set(ids)&set(self.a['holdout_ids']))
    def test_32_cold_cost_not_hidden_by_horizon(self):
        from fractions import Fraction as Q
        for s in config()['scenarios']:
            self.assertGreater(Q(s['step_fee'])*512+Q(s['calibration_fee'])*16,0)
        self.assertEqual(self.prior['actual_updates'],512)


if __name__=='__main__':unittest.main()
