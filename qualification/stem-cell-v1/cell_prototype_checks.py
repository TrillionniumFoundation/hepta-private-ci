"""Synthetic mechanism checks; real public observations are reported separately."""
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

from cell_anchor_study import execute as anchor_execute
from cell_conditional_study import execute as conditional_execute, review as conditional_review
from cell_consolidation import ConsolidationConfig, metrics, select_retained, ARMS as ORIGINAL
from cell_consolidation_study import execute as base_execute
from cell_consolidation_checks import fixture
from cell_prototype_gate import (ARMS, FOLDS, JointFloor, fit_geometry_candidates,
    geometry_fit, geometry_logits, joint_select, training_folds)
from cell_prototype_study import ALL_ARMS, execute, independent_forward, packets, review
from development_study import prepare_views
from development_study_data import canonical, phase
from model_runner import build_head


class PrototypeMath(unittest.TestCase):
    def setUp(self):
        threads=torch.get_num_threads(); torch.set_num_threads(1); self.addCleanup(torch.set_num_threads,threads)
        self.rows,self.x=fixture(); self.inputs,_=prepare_views(self.rows)
        self.config=ConsolidationConfig(classes=4,old_classes=(0,1),steps=12,memory_per_class=8)
        self.truth={r['sample_id']:r['label'] for r in self.rows if phase(r) in ('base','adapt')}
        with torch.random.fork_rng():
            torch.manual_seed(9)
            self.teachers={n:build_head(torch,8,4,'film',16384)[0].state_dict() for n in ('frozen','new_only')}

    def fit(self): return fit_geometry_candidates(self.inputs,self.truth,self.x,self.config,self.teachers)

    def test_fit_census_and_frozen_teachers(self):
        original=deepcopy(self.teachers); x=self.x.clone()
        models,mean,scale,costs=self.fit()
        self.assertTrue(torch.equal(x,self.x))
        for n,t in original.items(): self.assertTrue(all(torch.equal(v,self.teachers[n][k]) for k,v in t.items()))
        for n,c in costs['arms'].items():
            self.assertEqual(c['statistics_fits'],9); self.assertEqual(c['optimizer_steps'],0)
            self.assertEqual(c['cv_prediction_rows'],c['training_feature_rows']*8)
            self.assertTrue(all(self.inputs[i]['phase'] in ('base','adapt') for i in c['training_indices']))
        self.assertEqual(costs['current_encoder_calls'],0)

    def test_parameter_size_and_standalone_control(self):
        models,mean,scale,c=self.fit(); mm=packets(models)
        self.assertEqual(sum(v.numel() for v in mm['prototype_memory'].values()),72)
        self.assertEqual(sum(v.numel() for v in mm['geometry_memory'].values()),36)
        for n,t in mm.items():
            x=(self.x[:4]-mean)/scale
            a=geometry_logits(t,x,self.config,conditional=n.startswith('prototype_'))
            b=independent_forward(t,x,self.config,n.startswith('prototype_'))
            self.assertTrue(torch.allclose(a,b,atol=1e-5))

    def test_grouped_folds_keep_aliases_together(self):
        y=torch.arange(4).repeat_interleave(8); groups=[f'g{i}' for i in range(32)]
        ids=training_folds(torch.cat((y,y)),groups+groups,4)
        self.assertTrue(torch.equal(ids[:32],ids[32:])); self.assertEqual(set(ids.tolist()),set(range(4)))

    def test_conflicting_or_insufficient_groups_are_not_filled_in(self):
        y=torch.arange(4).repeat_interleave(8); groups=[f'g{i}' for i in range(32)]; groups[-1]=groups[0]
        with self.assertRaises(ValueError): training_folds(y,groups,4)
        with self.assertRaises(ValueError): training_folds(torch.arange(4),['a','b','c','d'],4)

    def test_duplicate_sources_do_not_reweight_geometry(self):
        y=torch.arange(4).repeat_interleave(8); groups=[f'g{i}' for i in range(32)]
        x=torch.randn(32,8,generator=torch.Generator().manual_seed(40))
        a=geometry_fit(x,y,groups,4,1.0)
        b=geometry_fit(torch.cat((x,x[:8])),torch.cat((y,y[:8])),groups+groups[:8],4,1.0)
        self.assertTrue(all(torch.equal(v,w) for v,w in zip(a,b)))

    def test_fold_assignment_is_input_order_invariant(self):
        y=torch.arange(4).repeat_interleave(8); groups=[str(i) for i in range(32)]
        a=training_folds(y,groups,4); order=torch.arange(31,-1,-1)
        b=training_folds(y[order],[groups[i] for i in order],4)
        self.assertTrue(torch.equal(a[order],b))

    def test_evaluation_features_do_not_fit_statistics(self):
        a=self.fit()[0]; changed=self.x.clone()
        ids=[i for i,r in enumerate(self.rows) if phase(r) in ('calibration','held_out')]; changed[ids]+=500
        b=fit_geometry_candidates(self.inputs,self.truth,changed,self.config,self.teachers)[0]
        self.assertTrue(all(torch.equal(v,b[n][k]) for n,t in a.items() for k,v in t.items()))

    def test_extra_evaluation_label_fails_before_geometry(self):
        t=dict(self.truth); t[self.rows[-1]['sample_id']]=0
        with patch('cell_prototype_gate.geometry_fit',side_effect=AssertionError('must preflight')):
            with self.assertRaises(ValueError): fit_geometry_candidates(self.inputs,t,self.x,self.config,self.teachers)

    def test_cv_validation_rows_excluded_from_each_fit(self):
        from cell_prototype_gate import geometry_fit as original
        seen=[]
        def wrapped(x,y,g,k,s): seen.append(tuple(g)); return original(x,y,g,k,s)
        with patch('cell_prototype_gate.geometry_fit',side_effect=wrapped): _,_,_,costs=self.fit()
        for j,name in enumerate(('memory','all_old')):
            c=costs['arms'][name]; gs=[self.inputs[i]['source_group'] for i in c['training_indices']]
            for f in range(4):
                held={g for g,fold in zip(gs,c['folds']) if fold==f}
                self.assertFalse(set(seen[j*9+f])&held)

    def test_disconnected_group_geometry_not_single_linear_boundary(self):
        centers=torch.tensor([[-2.,0.],[2.,0.],[0.,-2.],[0.,2.]])
        x=centers.repeat_interleave(8,0)+torch.randn(32,2,generator=torch.Generator().manual_seed(2))*.1
        y=torch.arange(4).repeat_interleave(8); gs=[str(i) for i in range(32)]
        w,b,c=geometry_fit(x,y,gs,4,1.0)
        raw=(centers.double()-c)@w.T+b
        self.assertEqual(raw.argmax(1).tolist(),[0,1,2,3])

    def test_bad_feature_dtype_and_nonfinite_tensor_refused(self):
        for x in (self.x.double(),self.x*float('nan')):
            with self.assertRaises(ValueError): fit_geometry_candidates(self.inputs,self.truth,x,self.config,self.teachers)
        mm=packets(self.fit()[0]); t=mm['prototype_memory']; t['routing_bias'][0]=float('inf')
        with self.assertRaises(ValueError): geometry_logits(t,self.x[:4],self.config,conditional=True)

    def test_group_conditionals_preserved_and_no_task_id(self):
        mm,mean,scale,_=self.fit(); t=mm['memory']; x=(self.x[:12]-mean)/scale
        y=geometry_logits(t,x,self.config,conditional=True); raw=x@t['weight'].T+t['bias']
        self.assertTrue(torch.allclose(y.exp().sum(1),torch.ones(12),atol=1e-6))
        for c,d in ((0,1),(2,3)): self.assertTrue(torch.allclose(y[:,c]-y[:,d],raw[:,c]-raw[:,d],atol=1e-5))

    def test_large_common_routing_offset_stays_normalized(self):
        t=packets(self.fit()[0])['prototype_memory'];t['routing_weight'].zero_();t['routing_bias'].fill_(1e30)
        a=geometry_logits(t,self.x[:4],self.config,conditional=True)
        b=independent_forward(t,self.x[:4],self.config,True)
        self.assertTrue(torch.allclose(a,b,atol=1e-5))
        self.assertTrue(torch.allclose(b.exp().sum(1),torch.ones(4),atol=1e-5))

    def scores(self,new_accuracy):
        ref={'per_class':{str(k):{'groups':20,'accuracy':1. if k<2 else 0.,'brier':.01 if k<2 else 1.5} for k in range(4)},
             'old':{'accuracy':1.,'brier':.01},'new':{'accuracy':0.,'brier':1.5}}
        cand=deepcopy(ref); cand['new']={'accuracy':new_accuracy,'brier':.01}
        for k in (2,3): cand['per_class'][str(k)].update(accuracy=new_accuracy,brier=.01)
        return {'frozen':ref,'candidate':cand}

    def test_near_frozen_false_progress_is_rejected(self):
        s=self.scores(.05); all_old={n:deepcopy(s['candidate'] if n!='frozen' else s['frozen']) for n in ORIGINAL}
        self.assertNotEqual(select_retained(all_old,self.config)['selected_arm'],'frozen')
        actual=joint_select(s,self.config)
        self.assertEqual(actual['selected'],'frozen'); self.assertFalse(actual['qualified'])

    def test_useful_positive_candidate_passes(self):
        r=joint_select(self.scores(.95),self.config)
        self.assertEqual(r['selected'],'candidate'); self.assertTrue(r['qualified']); self.assertFalse(r['production_authorized'])

    def test_per_class_floor_and_bad_probability_cannot_hide_in_mean(self):
        for key,value in (('accuracy',.5),('brier',.3),('accuracy',float('nan'))):
            s=self.scores(.95); s['candidate']['per_class']['2'][key]=value
            if value!=value:
                with self.assertRaises(ValueError): joint_select(s,self.config)
            else: self.assertFalse(joint_select(s,self.config)['qualified'])
        with self.assertRaises(ValueError): JointFloor(minimum_new_accuracy=True).validate()


class PrototypeStudy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.threads=torch.get_num_threads();torch.set_num_threads(1)
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name)
        cls.rows,cls.x=fixture();cls.origin={'synthetic_only':True}
        cls.cfg=ConsolidationConfig(classes=4,old_classes=(0,1),steps=12,memory_per_class=8)
        cls.base,cls.anchor,cls.conditional,cls.initial=[cls.root/n for n in ('base','anchor','conditional','initial')]
        base_execute(cls.rows,cls.x,cls.origin,cls.base,cls.cfg)
        anchor_execute(cls.rows,cls.x,cls.origin,cls.base,cls.anchor)
        conditional_execute(cls.rows,cls.x,cls.origin,cls.base,cls.anchor,cls.conditional)
        execute(cls.rows,cls.x,cls.origin,cls.base,cls.anchor,cls.conditional,cls.initial)

    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup();torch.set_num_threads(cls.threads)

    def setUp(self):
        self.tmpcase=tempfile.TemporaryDirectory();self.addCleanup(self.tmpcase.cleanup)
        self.folder=Path(self.tmpcase.name)/'copy';shutil.copytree(self.initial,self.folder)

    def verify(self): return review(self.rows,self.x,self.origin,self.base,self.anchor,self.conditional,self.folder)

    def rewrite(self,name,obj,field):
        raw=canonical(obj);(self.folder/name).write_bytes(raw);run=json.loads((self.folder/'run.json').read_text())
        run[field]=hashlib.sha256(raw).hexdigest();(self.folder/'run.json').write_bytes(canonical(run))

    def test_all_eighteen_controls_reconstruct(self):
        r=self.verify();self.assertEqual(set(r['scores']['held_out']),set(ALL_ARMS))
        self.assertEqual(r['prediction_rows'],64*18);self.assertEqual(r['argmax_reversals'],0)

    def test_parent_review_calibration_only_default_unchanged(self):
        rows=deepcopy(self.rows)
        for r in rows:
            if phase(r)=='held_out':r.pop('label')
        r=conditional_review(rows,self.x,self.origin,self.base,self.anchor,self.conditional,score_held_out=False)
        self.assertEqual(set(r['scores']),{'calibration'});self.assertEqual(r['held_out_error_decomposition'],{})
        with self.assertRaises(ValueError): conditional_review(rows,self.x,self.origin,self.base,self.anchor,self.conditional,score_held_out=1)

    def test_removed_or_permuted_test_truth_does_not_change_candidates(self):
        for remove in (True,False):
            rows=deepcopy(self.rows)
            for r in rows:
                if phase(r)=='held_out':
                    if remove:r.pop('label')
                    else:r['label']=(r['label']+1)%4
            out=Path(self.tmpcase.name)/str(remove)
            execute(rows,self.x,self.origin,self.base,self.anchor,self.conditional,out)
            for n in ('predictions.json',*[f'{a}.safetensors' for a in ARMS]):self.assertEqual((out/n).read_bytes(),(self.initial/n).read_bytes())
            self.assertEqual(json.loads((out/'selection.json').read_text()),json.loads((self.initial/'selection.json').read_text()))

    def test_rehashed_predictions_missing_rows_and_extra_labels_refused(self):
        original=json.loads((self.folder/'predictions.json').read_text())
        for mode in ('logit','missing','label'):
            p=deepcopy(original)
            if mode=='logit':p[-1]['logits'][0]+=.1
            if mode=='missing':p.pop()
            if mode=='label':p[0]['label']=0
            self.rewrite('predictions.json',p,'predictions_sha256')
            with self.subTest(mode=mode),self.assertRaises(ValueError):self.verify()

    def test_rehashed_training_grid_partition_and_cost_refused(self):
        original=json.loads((self.folder/'training.json').read_text())
        for mode in ('grid','partition','cost'):
            p=deepcopy(original);c=p['arms']['memory']
            if mode=='grid':c['grid'][0]['group_balanced_binary_log_loss']+=.1
            if mode=='partition':c['training_indices'][0]=999
            if mode=='cost':c['conditional_parameters']=0
            self.rewrite('training.json',p,'training_sha256')
            with self.subTest(mode=mode),self.assertRaises(ValueError):self.verify()

    def test_rehashed_checkpoint_change_not_hidden_by_consistent_predictions(self):
        n='prototype_memory';t=load((self.folder/f'{n}.safetensors').read_bytes());t['routing_bias'][0]+=.1
        raw=save(t);(self.folder/f'{n}.safetensors').write_bytes(raw)
        s=json.loads((self.folder/'selection.json').read_text());s['checkpoints'][n]=hashlib.sha256(raw).hexdigest()
        self.rewrite('selection.json',s,'selection_sha256')
        with self.assertRaises(ValueError):self.verify()

    def test_relaxed_floor_and_changed_winner_refused(self):
        s=json.loads((self.folder/'selection.json').read_text());s['selected']='invented'
        self.rewrite('selection.json',s,'selection_sha256')
        with self.assertRaises(ValueError):self.verify()

    def test_rehashed_relaxed_new_task_floor_is_refused(self):
        p=json.loads((self.folder/'plan.json').read_text());p['joint_floor']['minimum_new_accuracy']=.01
        self.rewrite('plan.json',p,'plan_sha256')
        with self.assertRaises(ValueError):self.verify()

    def test_failed_and_existing_output_and_symlink_refused(self):
        with self.assertRaises(FileExistsError):execute(self.rows,self.x,self.origin,self.base,self.anchor,self.conditional,self.folder)
        p=self.folder/'prototype_memory.safetensors';p.unlink();p.symlink_to(self.initial/p.name)
        with self.assertRaises(ValueError):self.verify()
        (self.folder/'FAILED.json').write_text('{}')
        with self.assertRaises(ValueError):self.verify()


if __name__=='__main__':unittest.main()
