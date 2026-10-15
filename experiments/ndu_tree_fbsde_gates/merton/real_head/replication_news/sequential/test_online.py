"""Adversarial pre-execution tests, including genuine original-source SGD."""
from __future__ import annotations
import contextlib
import copy
import io
import os
import tempfile
import unittest
from fractions import Fraction as Q
from pathlib import Path
from unittest.mock import patch
import numpy as np
from control import decision, select, validate, utility, alpha_for, rational
from online import config, lifecycle, setup, Trainer, run, encode, loads, packet, sha
from audit_online import reference_decision, audit
from material_news import prepare
from trial_news import fit


class Rules(unittest.TestCase):
    def setUp(self):
        self.s = config()['scenarios'][0]
        self.h = [{'step':0,'counts':[1,2,2,5]}]

    def test_budget_before_optimizer(self):
        self.assertEqual(decision(self.h,config()['scenarios'][3],'neutral')['reason'],'hard_budget')

    def test_perfect_outcome_rejection_before_pilot(self):
        self.assertEqual(decision(self.h,config()['scenarios'][1],'ndu')['reason'],'perfect_payoff_cannot_repay')

    def test_positive_headroom_only_authorizes_bounded_exploration(self):
        r = decision(self.h,self.s,'neutral')
        self.assertEqual((r['reason'],r['to_step']),('bounded_first_pilot',8))

    def test_plateau_stops_before128(self):
        h = self.h + [{'step':8,'counts':[7,6,6,6]},{'step':32,'counts':[7,6,6,6]}]
        self.assertEqual(decision(h,config()['scenarios'][2],'ndu')['reason'],'empirical_slope_stop')
        self.assertEqual(decision(h,self.s,'ndu')['reason'],'perfect_payoff_cannot_repay')
        self.assertEqual(select(h,self.s,'ndu'),8)

    def test_sunk_cost_not_recharged_in_next_quote(self):
        h = self.h + [{'step':8,'counts':[7,6,6,6]}]
        self.assertEqual(Q(decision(h,self.s,'neutral')['next_quote']),Q(24,256)+Q(1,1024))

    def test_declining_empirical_utility_stops(self):
        h=[{'step':0,'counts':[6]*4},{'step':8,'counts':[5]*4}]
        self.assertEqual(decision(h,self.s,'neutral')['action'],'stop')
        self.assertEqual(select(h,self.s,'neutral'),0)

    def test_perfect_payoff_ceiling_on_exact_grid(self):
        for n in range(9):
            for price in (Q(0),Q(1,256),Q(1,8),Q(1)):
                s={**self.s,'step_fee':str(price)}
                h=[{'step':0,'counts':[n]*4}]
                r=decision(h,s,'neutral')
                if r['reason']=='perfect_payoff_cannot_repay':
                    self.assertLessEqual(1-Q(r['next_quote']),Q(n,8))

    def test_independent_rule_matches_many_prefixes(self):
        rng=np.random.default_rng(1427)
        for _ in range(150):
            n=int(rng.integers(1,5))
            h=[{'step':s,'counts':rng.integers(0,9,size=4).tolist()} for s in (0,8,32,128)[:n]]
            for p in ('neutral','fixed','ndu'):
                self.assertEqual(decision(h,self.s,p),reference_decision(h,self.s,p))

    def test_no_claim_plateau_proves_future_optimality(self):
        h=[{'step':0,'counts':[4]*4},{'step':8,'counts':[4]*4}]
        self.assertEqual(decision(h,self.s,'neutral')['action'],'stop')
        # Constructed delayed improvement: the stopped policy cannot know it.
        self.assertGreater(1-Q(128,256),Q(4,8)-Q(8,256))

    def test_foreign_or_future_fields_rejected(self):
        for key in ('future_counts','holdout_labels','future_weights'):
            h=copy.deepcopy(self.h);h[0][key]=[8]*4
            with self.assertRaises(ValueError):decision(h,self.s,'ndu')

    def test_invalid_quotes_and_flags_rejected(self):
        for x in (True,0.1,-1,'-1/2',None):
            with self.assertRaises(ValueError):rational(x)
        for patcher in ({'budget':True},{'horizon':0},{'step_fee':'-1'},{'extra':0}):
            with self.assertRaises(ValueError):decision(self.h,{**self.s,**patcher},'ndu')

    def test_nonprefix_or_fractional_observation_rejected(self):
        for h in ([{'step':8,'counts':[1]*4}],
                  [{'step':0,'counts':[1]*4},{'step':32,'counts':[2]*4}],
                  [{'step':0,'counts':[True]*4}], [{'step':0,'counts':[1.0]*4}]):
            with self.assertRaises(ValueError):decision(h,self.s,'ndu')

    def test_alpha_is_bounded_and_responds_to_observed_data(self):
        for counts in ([0]*4,[8]*4):
            a=alpha_for([{'step':0,'counts':counts}],'ndu')
            self.assertLessEqual(a,Q(1,2));self.assertGreaterEqual(a,0)
        self.assertNotEqual(alpha_for(self.h,'ndu'),alpha_for([{'step':0,'counts':[8]*4}],'ndu'))


class Physical(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.archive=Path(os.environ['NEWS_ARCHIVE'])
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name)
        cls.material=cls.root/'material';prepare(cls.archive,cls.material)
        cls.a,_=packet(cls.material/'worker.npz');_,_,cls.x=setup(cls.a)
        cls.run_dir=cls.root/'run'
        with contextlib.redirect_stdout(io.StringIO()):run(cls.material,cls.run_dir)
        cls.seal=loads((cls.run_dir/'sealed.json').read_bytes())

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def test_real_incremental_sgd_equals_original(self):
        trainer=Trainer(self.x['train'],self.a['y_train'],128)
        ref,_=fit(self.x['train'],self.a['y_train'],(0,8,32,128))
        for k in (8,32,128):
            trainer.advance(k);np.testing.assert_array_equal(trainer.weights,ref[k])

    def test_no_gradient_call_when_preflight_refuses(self):
        for scenario in (config()['scenarios'][1],config()['scenarios'][3]):
            with patch.object(Trainer,'step',side_effect=AssertionError('forbidden gradient')):
                r=lifecycle(self.a,self.x,'sequential_ndu',scenario,lambda e:None)
                self.assertEqual(r['actual_steps'],0)

    def test_actual_step_counter_stops_not_just_output_checkpoint(self):
        observed=[];old=Trainer.step
        def spy(t):observed.append(t.updates);old(t)
        with patch.object(Trainer,'step',spy):
            r=lifecycle(self.a,self.x,'sequential_ndu',config()['scenarios'][0],lambda e:None)
        self.assertEqual(observed,list(range(32)))
        self.assertEqual((r['actual_steps'],r['selected_steps']),(32,8))

    def test_fixed8_does_not_pay_search(self):
        r=lifecycle(self.a,self.x,'fixed8',config()['scenarios'][0],lambda e:None)
        self.assertEqual((r['actual_steps'],r['calibration_calls']),(8,0))
        self.assertEqual(set(r['checkpoints']),{'8'})

    def test_full_search_is_still_actually128(self):
        r=lifecycle(self.a,self.x,'full_search',config()['scenarios'][0],lambda e:None)
        self.assertEqual((r['actual_steps'],r['selected_steps']),(128,8))

    def test_training_failure_never_gets_success_seal(self):
        bad=self.root/'interrupted'
        with patch.object(Trainer,'step',side_effect=RuntimeError('injected failure')):
            with self.assertRaises(RuntimeError):run(self.material,bad)
        self.assertFalse((bad/'sealed.json').exists())
        self.assertIn(b'failure',(bad/'attempts.jsonl').read_bytes())

    def test_both_worker_and_head_are_unchanged_outside_fit(self):
        before={k:v.copy() for k,v in self.a.items()}
        lifecycle(self.a,self.x,'sequential_ndu',config()['scenarios'][0],lambda e:None)
        for k,v in before.items():np.testing.assert_array_equal(v,self.a[k])

    def test_full_original_scalar_replay(self):
        with contextlib.redirect_stdout(io.StringIO()):
            r=audit(self.archive,self.material,self.run_dir,self.root/'audit.json')
        self.assertEqual(r['verified_lifecycles'],96)
        self.assertEqual(r['actual_optimizer_updates'],2280)
        self.assertFalse(r['prepilot_positive_roi_proved'])

    def reject(self,mutate):
        import shutil
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'run';shutil.copytree(self.run_dir,root)
            seal=copy.deepcopy(self.seal);mutate(seal)
            (root/'sealed.json').write_bytes(encode(seal))
            for r in seal['rows']:
                (root/f"{r['repeat']}-{r['scenario']}-{r['arm']}.json").write_bytes(encode(r))
            with self.assertRaises(ValueError):audit(self.archive,self.material,root,Path(td)/'a.json')

    def test_missing_lifecycle_rejected(self):self.reject(lambda s:s['rows'].pop())
    def test_extra_lifecycle_rejected(self):self.reject(lambda s:s['rows'].append(s['rows'][0]))
    def test_forged_real_model_claim_rejected(self):self.reject(lambda s:s.update(fresh_encoder_calls=1))
    def test_source_tamper_rejected(self):self.reject(lambda s:s['source_sha256'].update({'control.py':'0'*64}))
    def test_forged_work_rejected(self):self.reject(lambda s:s['rows'][1].update(actual_steps=0))
    def test_unexecuted_checkpoint_rejected(self):self.reject(lambda s:s['rows'][0]['checkpoints'].update({'128':s['rows'][0]['weights']}))
    def test_future_observation_rejected(self):self.reject(lambda s:s['rows'][4]['history'].append({'step':128,'counts':[8]*4}))
    def test_fractional_count_not_accepted_as_integer(self):
        self.reject(lambda s:s['rows'][4]['history'][0]['counts'].__setitem__(0,1.0))
    def test_parameter_tamper_rejected(self):self.reject(lambda s:s['rows'][1]['weights'][0].__setitem__(0,999))
    def test_quote_or_decision_tamper_rejected(self):
        def bad(s):
            r=next(r for r in s['rows'] if r['arm']=='sequential_ndu')
            next(e for e in r['events'] if e['kind']=='decision')['next_quote']='0'
        self.reject(bad)
    def test_missing_phase_rejected(self):self.reject(lambda s:s['rows'][1]['phases'].clear())
    def test_negative_timing_rejected(self):self.reject(lambda s:s['rows'][1].update(cpu_ns=-1))
    def test_unsafe_output_reuse_rejected(self):
        with self.assertRaises(FileExistsError):run(self.material,self.run_dir)
    def test_worker_has_no_holdout_label_field(self):self.assertNotIn('y_holdout',self.a)


if __name__=='__main__':unittest.main()
