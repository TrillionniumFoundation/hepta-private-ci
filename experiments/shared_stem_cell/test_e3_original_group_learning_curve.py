"""Physical HEAD-only CPU validation; artificial source groups, no real model."""
import copy
import hashlib
import json
import unittest
from unittest.mock import patch
import numpy as np
import torch

from e1_matched_gated_head import run_probe
from e3_original_group_learning_curve import forward_study,group_plan,BUDGETS,SEEDS,KINDS
from e3_group_learning_review import review,sha_state,SHAPES


class OriginalGroupCurveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel='4'*64
        cls.rows=[]
        for group in range(12):
            for i in range(4):
                cls.rows.append({'split':'train','condition':'original','source_group':f'group-{group}',
                                 'label':(i+group)%2})
        for group in range(4):
            for i in range(2):
                cls.rows.append({'split':'calibration','condition':'original','source_group':f'cal-{group}',
                                 'label':i})
        cls.held=[]
        for group in range(8):
            for i in range(2):
                cls.held.append({'split':'test','condition':'original','source_group':f'held-{group}'})
        rng=np.random.default_rng(31)
        cls.x=rng.normal(0,0.2,(len(cls.rows)+len(cls.held),384)).astype(np.float32)
        train=list(range(48));cal=list(range(48,56));blind=list(range(56,72))
        _,cls.parent=run_probe(cls.x,train,[cls.rows[i]['label'] for i in train],
                               cal,[cls.rows[i]['label'] for i in cal],blind)
        cls.report,cls.weights=forward_study(cls.x,cls.parent,cls.rows,cls.held,cls.panel)

    def checked(self, report=None,weights=None,features=None,rows=None,held=None,parent=None):
        return review(self.x if features is None else features,
                      self.parent if parent is None else parent,
                      self.rows if rows is None else rows,
                      self.held if held is None else held,
                      self.panel,self.report if report is None else report,
                      self.weights if weights is None else weights)

    def test_complete_physical_sgd_and_independent_numpy_replay(self):
        result=self.checked()
        self.assertEqual(result['validated_records'],18)
        self.assertEqual(result['original_group_budgets'],[4,8,12])
        self.assertTrue(result['original_full_budget_e1_parity'])
        self.assertLess(result['maximum_weight_disagreement'],3e-5)
        self.assertLess(result['maximum_probability_disagreement'],3e-5)

    def test_matched_parent_full_budget_trained_weights(self):
        for seed in SEEDS:
            for kind in KINDS:
                for field in SHAPES:
                    np.testing.assert_allclose(self.weights[f'b12.seed{seed}.{kind}.{field}'],
                                               self.parent[f'seed{seed}.trained_{kind}.{field}'],
                                               atol=1e-6,rtol=0)

    def test_nested_group_budgets_without_label_sorting(self):
        p=group_plan(self.rows,self.held,self.panel)
        self.assertEqual([len(p['budgets'][str(n)]['train_groups']) for n in BUDGETS],[4,8,12])
        self.assertEqual(set(p['budgets']['4']['train_groups']).issubset(p['budgets']['8']['train_groups']),True)
        self.assertEqual(set(p['budgets']['8']['train_groups']).issubset(p['budgets']['12']['train_groups']),True)
        self.assertEqual(len(set(p['source_group_order'])),12)
        self.assertNotIn('train_labels',self.report['plan']['budgets']['4'])
        self.assertNotIn('calibration_labels',self.report['plan'])
        self.assertIs(self.report['original_human_held_labels_read'],False)

    def test_source_selection_stable_under_panel_digest_or_label_changes(self):
        # The original panel_id is derived from fit content INCLUDING labels;
        # earlier salted selection could leak TRAIN-label identity into budgets.
        base=group_plan(self.rows,self.held,self.panel)
        changed_panel=group_plan(self.rows,self.held,'f'*64)
        altered=copy.deepcopy(self.rows)
        for row in altered:
            if row['split']=='train':
                row['label']=1-row['label']
        changed_labels=group_plan(altered,self.held,self.panel)
        assert base['selection']=='sha256(fixed-domain:source_group)-ascending-label-independent-v2'
        for current in (changed_panel,changed_labels):
            self.assertEqual(current['source_group_order'],base['source_group_order'])
            for budget in BUDGETS:
                self.assertEqual(current['budgets'][str(budget)]['train_groups'],
                                 base['budgets'][str(budget)]['train_groups'])
                self.assertEqual(current['budgets'][str(budget)]['train_indices'],
                                 base['budgets'][str(budget)]['train_indices'])

    def test_each_budget_repeats_exact_optimizer_steps_without_extra_encoder_calls(self):
        self.assertEqual(self.report['additional_encoder_forwards'],0)
        self.assertEqual(self.report['projection_extra_physical_forwards'],1)
        self.assertEqual(self.report['projection_extra_mac'],len(self.x)*384*128)
        for r in self.report['records']:
            self.assertEqual(r['optimizer_updates'],40)
            self.assertEqual(r['head_parameter_count'],4145)
            self.assertEqual(r['train_row_exposures'],40*r['training_rows'])
            self.assertEqual(len(r['blind_predictions']),len(self.held))

    def test_original_feature_mutation_refused(self):
        x=self.x.copy();x[1,2]+=.4
        with self.assertRaises(ValueError):self.checked(features=x)

    def test_wrong_shared_projection_or_parent_refused(self):
        parent=copy.deepcopy(self.parent);parent['shared_projection'][2,2]+=.1
        with self.assertRaises(ValueError):self.checked(parent=parent)
        parent=copy.deepcopy(self.parent);del parent['seed41.frozen_gated.a.weight']
        with self.assertRaises((KeyError,ValueError)):self.checked(parent=parent)

    def test_changed_and_rehashed_head_rejected(self):
        w=copy.deepcopy(self.weights);r=copy.deepcopy(self.report)
        w['b4.seed41.gated.out.bias']+=.05
        state={k:w['b4.seed41.gated.'+k] for k in SHAPES}
        for rec in r['records']:
            if (rec['budget_source_groups'],rec['seed'],rec['architecture'])==(4,41,'gated'):
                rec['final_sha256']=sha_state(state)
        with self.assertRaisesRegex(ValueError,'SGD replay'):self.checked(report=r,weights=w)

    def test_fabricated_training_cost_or_optimizer_updates_refused(self):
        for key,value in [('optimizer_updates',39),('train_row_exposures',0),('head_parameter_count',770),
                          ('train_wall_ms',float('nan')),('train_cpu_ms',-1.0)]:
            r=copy.deepcopy(self.report);r['records'][0][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.checked(report=r)

    def test_wrong_group_plan_and_train_label_refused(self):
        r=copy.deepcopy(self.report)
        r['plan']['budgets']['4']['train_indices']=[0]
        with self.assertRaises(ValueError):self.checked(report=r)
        rows=copy.deepcopy(self.rows);rows[0]['label']=1-rows[0]['label']
        with self.assertRaises(ValueError):self.checked(rows=rows)

    def test_nonfinite_truncated_and_rehashed_probabilities_refused(self):
        for item in ('nan','short','changed','greater'):
            r=copy.deepcopy(self.report)
            a=r['records'][0]['blind_predictions']
            if item=='nan':a[0]=float('nan')
            elif item=='short':a.pop()
            elif item=='changed':a[0]=0.95 if a[0]<.5 else .05
            else:a[0]=1.001
            with self.subTest(item=item),self.assertRaises(ValueError):self.checked(report=r)

    def test_mismatched_tensors_or_extra_parameter_refused(self):
        w=copy.deepcopy(self.weights)
        del w[next(iter(w))]
        with self.assertRaises(ValueError):self.checked(weights=w)
        w=copy.deepcopy(self.weights);w['injected']=np.ones(3,dtype=np.float32)
        with self.assertRaises(ValueError):self.checked(weights=w)

    def test_false_authority_or_zero_cost_refused(self):
        for key,value in [('authority','GRANTED'),('production_promotion_permitted',True),
                          ('statistical_winner_selected',True),('equal_full_lifecycle_cost_certified',True),
                          ('original_human_held_labels_read',True),('projection_extra_physical_forwards',0),
                          ('additional_encoder_forwards',1),('projection_extra_mac',0)]:
            r=copy.deepcopy(self.report);r[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.checked(report=r)

    def test_missing_both_labels_marks_budget_infeasible_not_zero_score(self):
        rows=copy.deepcopy(self.rows)
        selected=group_plan(rows,self.held,self.panel)['budgets']['4']['train_groups']
        for row in rows:
            if row['split']=='train' and row['source_group'] in selected:
                row['label']=0
        _,initial=run_probe(self.x,list(range(48)),[rows[i]['label'] for i in range(48)],
                            list(range(48,56)),[rows[i]['label'] for i in range(48,56)],list(range(56,72)))
        r,w=forward_study(self.x,initial,rows,self.held,self.panel)
        result=review(self.x,initial,rows,self.held,self.panel,r,w)
        self.assertEqual(result['budget_status']['4'],'infeasible_missing_both_labels')
        for rec in r['records'][:6]:
            self.assertEqual(rec['status'],'missing_both_labels')
            self.assertIsNone(rec['blind_predictions'])

    def test_no_held_truth_argument_or_torch_dependency_in_reviewer(self):
        import subprocess,sys
        from pathlib import Path
        done=subprocess.run([sys.executable,'-c',
            "import sys,e3_group_learning_review; assert 'torch' not in sys.modules; assert 'e3_original_group_learning_curve' not in sys.modules"],
            cwd=Path(__file__).parent,capture_output=True,text=True)
        self.assertEqual(done.returncode,0,done.stderr)
        with self.assertRaises(TypeError):forward_study(self.x,self.parent,self.rows,self.held,self.panel,held_labels=[0]*16)


if __name__=='__main__':unittest.main()
