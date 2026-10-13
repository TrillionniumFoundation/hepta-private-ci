"""Actual Reader execution and finite stopping math; no general NDU acceptance."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import torch

from experiments.shared_stem_cell import execution as e
from experiments.shared_stem_cell import controls as c
from experiments.shared_stem_cell import stopping as s
from experiments.shared_stem_cell import stopping_study as study


class StoppingTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(71)
            self.x = torch.randn(8, 4, 4)
            self.y = torch.arange(8) % 2
            self.model = c.RecurrentReader(4, 2).eval().requires_grad_(False)

    def test_backward_stops_at_good_middle_not_bad_terminal(self):
        p = torch.tensor([[[.6,.4], [.1,.9], [.6,.4]]]*16)
        labels = torch.ones(16, dtype=torch.long)
        with patch('torch.linalg.lstsq', wraps=torch.linalg.lstsq) as solve:
            rules, report = s.fit_rules(p, labels, step_cost=.05)
        self.assertEqual(solve.call_count, 4)
        self.assertEqual(s.trace_depths(p, rules['terminal_linear']).tolist(), [1]*16)
        self.assertEqual(s.trace_depths(p, rules['backward_linear']).tolist(), [2]*16)
        self.assertEqual({v['ridge_fits'] for v in report['diagnostics'].values()}, {2})

    def test_complementary_two_step_gain_not_greedy_one_step(self):
        p = torch.tensor([[[.6,.4], [.6,.4], [.1,.9]]]*16)
        rules, _ = s.fit_rules(p, torch.ones(16, dtype=torch.long), step_cost=.1)
        self.assertEqual(s.trace_depths(p, rules['backward_linear']).tolist(), [3]*16)

    def test_identical_information_positive_cost_stops(self):
        p = torch.tensor([[[.8,.2]]*4]*16)
        rules, _ = s.fit_rules(p, torch.zeros(16, dtype=torch.long), step_cost=.2)
        for rule in rules.values():
            self.assertEqual(s.trace_depths(p, rule).tolist(), [1]*16)

    def test_gate_fitting_does_not_mutate_trace_labels_or_rng(self):
        p, _ = s.read_trace(self.model, self.x)
        before, labels, rng = p.clone(), self.y.clone(), torch.get_rng_state().clone()
        s.fit_rules(p, self.y, step_cost=.02)
        self.assertTrue(torch.equal(p,before) and torch.equal(labels,self.y))
        self.assertTrue(torch.equal(rng,torch.get_rng_state()))

    def test_actual_stopped_reads_and_sunk_first_charge(self):
        rule = s.StopRule('fixed',4,2,.2,limit=1)
        with patch.object(self.model, 'step', wraps=self.model.step) as call:
            result = s.execute(self.model,self.x,rule)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(result['read_rows'], [list(range(8))])
        scored = s.score(result,self.y.tolist())
        self.assertEqual(scored['cell_transitions'],8)
        self.assertAlmostEqual(scored['net_utility'],scored['accuracy']-.2)

    def test_unread_suffix_cannot_change_already_stopped_output(self):
        rule = s.StopRule('fixed',4,2,0.,limit=1)
        other = self.x.clone()
        other[:,1:] = other[:,1:]*17+9
        first, second = s.execute(self.model,self.x,rule), s.execute(self.model,other,rule)
        self.assertEqual(first['probabilities'], second['probabilities'])
        self.assertEqual(first['depths'], second['depths'])

    def test_real_variable_exit_has_no_finished_rows_in_later_calls(self):
        # Use real Reader predictions to choose a fixed threshold for this mechanism test.
        p,_ = s.read_trace(self.model,self.x)
        q=p[:,0].max(-1).values
        threshold=float((q.min()+q.max())/2)
        rule=s.StopRule('confidence',4,2,.02,threshold=threshold)
        result=s.execute(self.model,self.x,rule)
        s.score(result,self.y.tolist())
        self.assertTrue(1 < len(result['read_rows'][1]) < len(self.x))
        for t,ids in enumerate(result['read_rows']):
            self.assertEqual(ids,[i for i,d in enumerate(result['depths']) if d>=t+1])

    def test_offline_trace_replay_matches_actual_execution_decisions(self):
        p,_=s.read_trace(self.model,self.x)
        rules,_=s.fit_rules(p,self.y,step_cost=.02)
        for rule in rules.values():
            actual=s.execute(self.model,self.x,rule)
            self.assertEqual(actual['depths'],s.trace_depths(p,rule).tolist())
            d=torch.tensor(actual['depths'])
            self.assertTrue(torch.allclose(torch.tensor(actual['probabilities']),
                            p[torch.arange(len(p)),d-1],atol=1e-6,rtol=1e-5))

    def test_model_features_and_global_rng_unchanged(self):
        weights,x,rng=e.parameters(self.model),self.x.clone(),torch.get_rng_state().clone()
        s.execute(self.model,self.x,s.StopRule('fixed',4,2,0.,limit=4))
        self.assertEqual(e.parameters(self.model),weights)
        self.assertTrue(torch.equal(self.x,x) and torch.equal(rng,torch.get_rng_state()))

    def test_whole_invalid_input_precedes_first_forward(self):
        damaged=self.x.clone();damaged[-1,-1,-1]=float('nan')
        with patch.object(self.model,'step',wraps=self.model.step) as call:
            with self.assertRaises(e.InputError):
                s.execute(self.model,damaged,s.StopRule('fixed',4,2,0.,limit=1))
        self.assertEqual(call.call_count,0)

    def test_invalid_rules_or_trainable_models_reject(self):
        for bad in (s.StopRule('unknown',4,2,0.),s.StopRule('fixed',4,2,0.,limit=True),
                    s.StopRule('fixed',4,2,float('nan'),limit=1),
                    s.StopRule('backward_linear',4,2,.1,coefficients=((0.,)*4,))):
            with self.assertRaises(e.InputError):
                s.execute(self.model,self.x,bad)
        self.model.requires_grad_(True)
        with self.assertRaises(e.InputError):
            s.execute(self.model,self.x,s.StopRule('fixed',4,2,0.,limit=1))

    def test_corrupt_rehashed_work_record_rejects(self):
        good=s.execute(self.model,self.x,s.StopRule('fixed',4,2,.02,limit=2))
        for field in ('depths','read_rows','cell_transitions','gate_rows','forward_calls'):
            bad=deepcopy(good)
            if field=='depths':bad[field][-1]=1
            elif field=='read_rows':bad[field][-1].pop()
            else:bad['cost'][field]+=1
            with self.assertRaises(e.InputError):s.score(bad,self.y.tolist())
        bad=deepcopy(good);bad['probabilities'].pop()
        with self.assertRaises(e.InputError):s.score(bad,self.y.tolist())

    def test_fixed_and_confidence_selection_only_uses_calibration(self):
        p=torch.tensor([[[.6,.4],[.1,.9],[.6,.4]]]*8)
        fixed,confidence,report=s.tune_simple(p,torch.ones(8,dtype=torch.long),step_cost=.01)
        self.assertEqual(fixed.limit,2)
        self.assertEqual(s.trace_depths(p,confidence).tolist(),[2]*8)
        self.assertEqual(len(report['rows']),9)

    def test_critic_probability_label_and_ridge_preflight(self):
        p,_=s.read_trace(self.model,self.x)
        for y in (self.y.float(),self.y[:-1],self.y+2):
            with self.assertRaises(e.InputError):s.fit_rules(p,y,step_cost=.02)
        with self.assertRaises(e.InputError):s.fit_rules(p*2,self.y,step_cost=.02)
        for ridge in (0.,float('nan'),True):
            with self.assertRaises(e.InputError):s.fit_rules(p,self.y,step_cost=.02,ridge=ridge)

    def test_existing_training_and_legacy_one_observation_still_work(self):
        rng=torch.get_rng_state().clone()
        model,report=c.fit_recurrent_reader(self.x,self.y,classes=2,steps=2)
        self.assertFalse(any(p.requires_grad for p in model.parameters()))
        self.assertEqual(report['training_transitions'],64)
        self.assertTrue(torch.equal(rng,torch.get_rng_state()))
        with patch('torch.optim.AdamW',wraps=torch.optim.AdamW) as optimizer:
            with self.assertRaises(e.InputError):
                c.recurrent_trial(self.x,self.y,self.x,self.y[:-1],self.x,classes=2,steps=2)
        self.assertEqual(optimizer.call_count,0)
        result=c.recurrent_trial(self.x[:,:1],self.y,self.x[:,:1],self.y,self.x[:,:1],classes=2,steps=2)
        self.assertEqual(len(result['predictions']),4)

    def test_original_public_encoder_width_remains_supported(self):
        # Existing real mmBERT-small entrypoint has width384, not the new stream limit256.
        x=torch.zeros(2,1,384);y=torch.tensor([0,1])
        result=c.recurrent_trial(x,y,x,y,x,classes=2,steps=1,depth=2)
        self.assertEqual(result['costs']['no_recurrence']['cell_transitions'],2)

    def test_strip_mapping_carries_only_declared_pixels(self):
        pixels=torch.arange(64).remainder(17).float()[None,:]
        observations=study.observations(pixels)
        self.assertEqual(observations.shape,(1,4,20))
        for t,k in enumerate(study.STRIP_ORDER):
            self.assertTrue(torch.equal(observations[0,t,:16],pixels[0,k*16:(k+1)*16]/16))
            self.assertEqual(observations[0,t,16:].argmax().item(),k)

    def test_content_duplicate_has_same_fold_without_labels(self):
        pixels=torch.arange(64).remainder(17).float().repeat(2,1)
        ids,folds=study.cohort(pixels)
        self.assertEqual(ids[0],ids[1]);self.assertEqual(folds[0],folds[1])

    def test_full_real_data_entrypoint_seals_every_seed_before_holdout_label_read(self):
        from sklearn.datasets import load_digits
        data=load_digits()
        _,folds=study.cohort(torch.tensor(data.data,dtype=torch.float32))
        original=data.target
        heldout_reads=[]
        with tempfile.TemporaryDirectory() as temp:
            output=Path(temp)/'run'
            class Guard:
                def __getitem__(self,key):
                    indices=[key] if isinstance(key,int) else key
                    if any(folds[i]=='holdout' for i in indices):
                        for seed in (17,29):
                            if not (output/f'predictions-{seed}.json').exists():
                                raise AssertionError('holdout label accessed before complete prediction seals')
                        heldout_reads.extend(indices)
                    return original[key]
            data.target=Guard()
            with patch('sklearn.datasets.load_digits',return_value=data):
                report=study.study(output,seeds=(17,29),steps=1)
            self.assertEqual(len(report['runs']),6)
            self.assertEqual(len(heldout_reads),report['fold_counts']['holdout'])
            self.assertTrue(all(len(r['scores'])==7 for r in report['runs']))
            self.assertTrue(all(r['encoder_calls']==0 for r in [report]))
            self.assertFalse(report['general_fbsde'])


if __name__=='__main__':
    unittest.main()
