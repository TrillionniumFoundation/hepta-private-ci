"""Synthetic conditional routing and artifact regressions, not model-quality proof."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import torch
from safetensors.torch import load, save

from cell_anchor_study import execute as execute_anchor, review as review_anchor
from cell_conditional_gate import (GATE_ARMS, LEARNED, OFFSETS, calibrate, conditional_logits,
                                   fit_gates, frozen_experts, shifted)
from cell_conditional_study import ALL_ARMS, execute, reconstructed, review
from cell_consolidation import ConsolidationConfig, metrics
from cell_consolidation_checks import fixture
from cell_consolidation_study import execute as execute_base
from development_study import prepare_views
from development_study_data import canonical, phase
from model_runner import build_head


class ConditionalMathChecks(unittest.TestCase):
    def setUp(self):
        threads = torch.get_num_threads(); torch.set_num_threads(1)
        self.addCleanup(torch.set_num_threads, threads)
        self.cfg = ConsolidationConfig(classes=4, old_classes=(0, 1), steps=12, memory_per_class=2)
        with torch.random.fork_rng():
            torch.manual_seed(77)
            self.teachers = {n: build_head(torch, 8, 4, 'film', 16384)[0].state_dict() for n in ('frozen', 'new_only')}
            self.x = torch.randn(30, 8)
        self.t = frozen_experts(self.teachers, 8, self.cfg)
        self.t.update(gate_weight=torch.arange(8)/10, gate_bias=torch.tensor([.3]))

    def test_probabilities_normalize_and_match_independent_equation(self):
        y = conditional_logits(self.t, self.x, self.cfg, 'gate_memory')
        self.assertTrue(torch.allclose(y.exp().sum(1), torch.ones(30), atol=1e-6))
        self.assertTrue(torch.allclose(y, reconstructed(self.t,self.x,self.teachers,self.cfg,'gate_memory'),atol=1e-6))

    def test_old_and_new_log_odds_are_unchanged_by_gate(self):
        raw = self.x@self.t['weight'].T+self.t['bias']
        for offset in OFFSETS:
            y = conditional_logits(shifted(self.t, offset), self.x, self.cfg, 'gate_memory')
            self.assertTrue(torch.allclose(y[:,0]-y[:,1],raw[:,0]-raw[:,1],atol=2e-6))
            self.assertTrue(torch.allclose(y[:,2]-y[:,3],raw[:,2]-raw[:,3],atol=2e-6))

    def test_unseen_extreme_gate_can_still_steal_old_prediction(self):
        t = deepcopy(self.t); t['gate_weight'].zero_(); t['gate_bias'].fill_(30)
        y = conditional_logits(t,self.x,self.cfg,'gate_memory')
        self.assertTrue((y.argmax(1)>=2).all())  # Conditional invariance is NOT no forgetting.

    def test_score_gate_initialization_reproduces_concat_probabilities(self):
        t = {k:v for k,v in self.t.items() if k in ('weight','bias')}
        expected = conditional_logits(t,self.x,self.cfg,'conditional_concat').softmax(-1)
        t.update(gate_weight=torch.ones(1),gate_bias=torch.zeros(1))
        y = conditional_logits(t,self.x,self.cfg,'gate_score_memory')
        self.assertTrue(torch.allclose(y.exp(),expected,atol=1e-6))
        self.assertTrue(torch.allclose(y,reconstructed(t,self.x,self.teachers,self.cfg,'gate_score_memory'),atol=1e-6))

    def test_constant_gate_and_concat_are_separate_strong_controls(self):
        t = {k:v for k,v in self.t.items() if k in ('weight','bias')}
        half = conditional_logits(t,self.x,self.cfg,'conditional_half')
        self.assertTrue(torch.allclose(half[:,:2].exp().sum(1),torch.full((30,),.5),atol=1e-6))
        self.assertTrue(torch.equal(conditional_logits(t,self.x,self.cfg,'conditional_concat'),self.x@t['weight'].T+t['bias']))

    def test_noncontiguous_old_class_schema(self):
        cfg = replace(self.cfg, old_classes=(0,2))
        t = frozen_experts(self.teachers,8,cfg); t.update(gate_weight=torch.zeros(8),gate_bias=torch.zeros(1))
        y = conditional_logits(t,self.x,cfg,'gate_memory')
        self.assertTrue(torch.allclose(y[:,[0,2]].exp().sum(1),torch.full((30,),.5),atol=1e-6))

    def test_bad_inventory_dtype_nonfinite_and_unknown_rule_refused(self):
        for t in ({**self.t, 'extra':torch.zeros(1)}, {k:v.double() for k,v in self.t.items()},
                  {**self.t,'gate_bias':torch.tensor([float('nan')])}):
            with self.assertRaises(ValueError): conditional_logits(t,self.x,self.cfg,'gate_memory')
        with self.assertRaises(ValueError): conditional_logits(self.t,self.x,self.cfg,'oracle')

    def test_finite_overflow_and_cancellation_are_not_hidden(self):
        for value in (3e38, 1e20):
            t = deepcopy(self.t); t['gate_weight'].zero_(); t['gate_bias'].fill_(value)
            with self.assertRaises(ValueError): conditional_logits(t,self.x,self.cfg,'gate_memory')

    def test_changed_frozen_rows_fail_independent_reconstruction(self):
        t=deepcopy(self.t); t['weight'][0,0]+=.01
        with self.assertRaises(ValueError): reconstructed(t,self.x,self.teachers,self.cfg,'gate_memory')

    def test_offset_requires_registered_value_and_never_mutates_input(self):
        saved=deepcopy(self.t); shifted(self.t,-2.)
        self.assertTrue(all(torch.equal(v,self.t[k]) for k,v in saved.items()))
        for value in (True, .3, float('nan')):
            with self.assertRaises(ValueError): shifted(self.t,value)

    def test_training_changes_only_gate_and_preserves_features_teachers(self):
        rows,x=fixture(); inputs,_=prepare_views(rows)
        truth={r['sample_id']:r['label'] for r in rows if phase(r) in ('base','adapt')}
        original=deepcopy(self.teachers); xx=x.clone()
        models,_,_,costs,part=fit_gates(inputs,truth,x,self.cfg,self.teachers)
        self.assertTrue(torch.equal(x,xx))
        for n,t in original.items(): self.assertTrue(all(torch.equal(v,self.teachers[n][k]) for k,v in t.items()))
        for n in LEARNED:
            self.assertTrue(torch.equal(models[n]['weight'],models['conditional_half']['weight']))
            self.assertTrue(torch.equal(models[n]['bias'],models['conditional_half']['bias']))
            self.assertGreater(float(models[n]['gate_weight'].abs().sum()),0)
            self.assertEqual(costs['arms'][n]['trainable_parameters'],2 if n=='gate_score_memory' else 9)
        self.assertEqual(costs['total_steps'],36)
        self.assertEqual(costs['arms']['gate_memory']['replay_indices'],part['memory'])

    def test_no_calibration_or_test_truth_at_training_boundary(self):
        rows,x=fixture(); inputs,_=prepare_views(rows)
        truth={r['sample_id']:r['label'] for r in rows if phase(r) in ('base','adapt')}
        truth[next(r['sample_id'] for r in rows if phase(r)=='calibration')]=0
        with patch('torch.optim.AdamW',side_effect=AssertionError('optimizer should not run')):
            with self.assertRaises(ValueError): fit_gates(inputs,truth,x,self.cfg,self.teachers)

    def test_positive_retention_case_and_no_supported_grid_fallback(self):
        cfg=self.cfg; x=torch.eye(4).repeat(3,1)
        t={'weight':torch.eye(4)*8,'bias':torch.zeros(4),
           'gate_weight':torch.tensor([-10.,-10.,10.,10.]),'gate_bias':torch.zeros(1)}
        y=torch.arange(4).repeat(3); groups=[str(i) for i in range(12)]
        reference_logits=x@t['weight'].T;reference_logits[:,2:]=-10
        reference=metrics(reference_logits,y,groups,cfg)
        _, report=calibrate(t,x,y,groups,reference,cfg,'gate_memory')
        self.assertTrue(report['supported'])
        t['gate_weight'].zero_()
        _, report=calibrate(t,x,y,groups,reference,cfg,'gate_memory')
        self.assertFalse(report['supported']);self.assertEqual(report['selected_offset'],0)


class ConditionalStudyChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.threads=torch.get_num_threads();torch.set_num_threads(1)
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name)
        cls.rows,cls.x=fixture();cls.origin={'synthetic_only':True}
        cls.cfg=ConsolidationConfig(classes=4,old_classes=(0,1),steps=12,memory_per_class=2)
        cls.base,cls.anchor,cls.initial=[cls.root/n for n in ('base','anchor','initial')]
        execute_base(cls.rows,cls.x,cls.origin,cls.base,cls.cfg)
        execute_anchor(cls.rows,cls.x,cls.origin,cls.base,cls.anchor)
        execute(cls.rows,cls.x,cls.origin,cls.base,cls.anchor,cls.initial)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup();torch.set_num_threads(cls.threads)

    def setUp(self):
        self.tmp_case=tempfile.TemporaryDirectory();self.addCleanup(self.tmp_case.cleanup)
        self.folder=Path(self.tmp_case.name)/'copy';shutil.copytree(self.initial,self.folder)

    def verify(self): return review(self.rows,self.x,self.origin,self.base,self.anchor,self.folder)

    def rewrite(self,name,obj,field):
        data=canonical(obj);(self.folder/name).write_bytes(data)
        run=json.loads((self.folder/'run.json').read_text());run[field]=hashlib.sha256(data).hexdigest()
        (self.folder/'run.json').write_bytes(canonical(run))

    def test_all_fourteen_controls_and_error_census_replay(self):
        result=self.verify()
        self.assertEqual(set(result['scores']['held_out']),set(ALL_ARMS))
        self.assertEqual(result['prediction_rows'],64*14)
        self.assertEqual(result['unique_held_out_inputs'],32)
        self.assertLess(result['max_abs_logit_error'],1e-5)
        self.assertFalse(result['global_no_forgetting_established'])

    def test_missing_held_out_truth_and_permuted_truth_leave_training_unchanged(self):
        for missing in (True,False):
            rows=deepcopy(self.rows)
            for r in rows:
                if phase(r)=='held_out':
                    if missing: r.pop('label')
                    else: r['label']=(r['label']+1)%4
            out=Path(self.tmp_case.name)/str(missing)
            execute(rows,self.x,self.origin,self.base,self.anchor,out)
            for name in ('predictions.json',*[f'{n}.safetensors' for n in GATE_ARMS],*[f'unshifted_{n}.safetensors' for n in LEARNED]):
                self.assertEqual((out/name).read_bytes(),(self.initial/name).read_bytes())
            a,b=[json.loads((p/'selection.json').read_text()) for p in (out,self.initial)]
            for k in ('selected_arm','grid','calibration_floors'): self.assertEqual(a[k],b[k])

    def test_parent_anchor_calibration_only_mode_never_requires_test_truth(self):
        rows=deepcopy(self.rows)
        for r in rows:
            if phase(r)=='held_out': r.pop('label')
        r=review_anchor(rows,self.x,self.origin,self.base,self.anchor,score_held_out=False)
        self.assertEqual(set(r['scores']),{'calibration'})
        with self.assertRaises(ValueError): review_anchor(rows,self.x,self.origin,self.base,self.anchor,score_held_out=1)

    def test_rehashed_prediction_forgery_refused(self):
        p=json.loads((self.folder/'predictions.json').read_text());p[-1]['logits'][0]+=.1
        self.rewrite('predictions.json',p,'predictions_sha256')
        with self.assertRaises(ValueError): self.verify()

    def test_rehashed_expert_mutation_refused(self):
        name='gate_memory';t=load((self.folder/f'{name}.safetensors').read_bytes());t['weight'][0,0]+=.02
        raw=save(t);(self.folder/f'{name}.safetensors').write_bytes(raw)
        s=json.loads((self.folder/'selection.json').read_text());s['checkpoints'][name]=hashlib.sha256(raw).hexdigest()
        self.rewrite('selection.json',s,'selection_sha256')
        with self.assertRaises(ValueError): self.verify()

    def test_rehashed_cost_offset_winner_or_grid_changes_refused(self):
        original=json.loads((self.folder/'selection.json').read_text())
        for mutation in ('cost','offset','winner','grid'):
            s=deepcopy(original)
            if mutation=='cost': s['costs']['arms']['gate_memory']['trainable_parameters']=0
            if mutation=='offset': s['grid']['gate_memory']['selected_offset']=19
            if mutation=='winner': s['selected_arm']='invented'
            if mutation=='grid': s['grid']['gate_memory']['grid'][0]['metrics']['old']['brier']+=.1
            self.rewrite('selection.json',s,'selection_sha256')
            with self.subTest(mutation=mutation),self.assertRaises(ValueError): self.verify()

    def test_source_implementation_grid_and_input_changes_refused(self):
        original=json.loads((self.folder/'plan.json').read_text())
        for key in ('implementation','input_digest','offsets'):
            p=deepcopy(original);p[key]={} if key=='implementation' else '0'*64 if key=='input_digest' else [0]
            self.rewrite('plan.json',p,'plan_sha256')
            with self.subTest(key=key),self.assertRaises(ValueError): self.verify()

    def test_missing_prediction_and_extra_gold_are_refused(self):
        original=json.loads((self.folder/'predictions.json').read_text())
        for missing in (True,False):
            p=deepcopy(original)
            if missing: p.pop()
            else: p[0]['label']=1
            self.rewrite('predictions.json',p,'predictions_sha256')
            with self.assertRaises(ValueError): self.verify()

    def test_failed_run_and_existing_output_cannot_become_success(self):
        with self.assertRaises(FileExistsError): execute(self.rows,self.x,self.origin,self.base,self.anchor,self.folder)
        (self.folder/'FAILED.json').write_text('{}')
        with self.assertRaises(ValueError): self.verify()

    def test_changed_source_and_symlinked_tensor_are_refused(self):
        with self.assertRaises(ValueError): review(self.rows,self.x,{'other':True},self.base,self.anchor,self.folder)
        path=self.folder/'gate_memory.safetensors';path.unlink();path.symlink_to(self.initial/path.name)
        with self.assertRaises(ValueError): self.verify()


if __name__=='__main__': unittest.main()
