"""Executable P0 semantic counterfactual fault tests: SYNTHETIC fixtures ONLY."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

from p0_multirc_semantic_material import (build, candidates, validate, canonical, sha,
  read, save, checked_source_hash, make_row, selected, Invalid, normalized,
  SCHEMA, COUNTS, CONDITIONS, PROTOCOL)
from p0_multirc_semantic_review import (review,REQUIRED,REVISIONS,metrics,numeric,
  original_label_audit)
from p0_multirc_semantic_execute import fit_head,run

A='a'*64
B='b'*64


def fixture_source(n=17,start=1):
    results=[]
    for i in range(start,start+n):
        passage=(f'Historical report number {i}: Alice visited Rome in June and Bob visited Paris in July. '
                 f'The travel officer confirmed Alice went to Rome and Bob went to Paris. '
                 f'Additional details in report number {i} mention the train departure and a meeting. ')
        qs=[('Which city did Alice visit?', [('Rome',1),('Paris',0)]),
            ('Which city did Bob visit?', [('Paris',1),('Rome',0)])]
        for qidx,(question,answers) in enumerate(qs):
            for aidx,(answer,label) in enumerate(answers):
                results.append({'paragraph':passage,'question':question,'answer':answer,
                                'label':label,'idx':{'paragraph':i,'question':qidx,'answer':aidx}})
    return results


def setup():
    train,val=fixture_source(17,1),fixture_source(17,100)
    fit,blind,owner=build(train,val,train_sha=A,validation_sha=B)
    return train,val,fit,blind,owner


def mocked_report(model,fit,blind,*,native=False):
    is_laya=model=='laya421_nochange'
    controls={}
    names=['laya_native_nochange'] if is_laya else ['frozen_head','trained_head']
    for arm in names:
        controls[arm]={'predictions':[
            {'case_id':r['case_id'],'view_sha256':r['view_sha256'],
             'positive_probability':.51 if r['condition']=='original' else .49,
             ('full_request_ms' if is_laya else 'head_request_ms'): .05}
            for r in blind['cases']]}
        if not is_laya:
            controls[arm]['head_sha256'] = ('a' if arm=='frozen_head' else 'b')*64
    width=384 if model in ('granite_97m_r2','mmbert_small') else 256
    param=width*2+2
    training=None if is_laya else {'parameter_count':param,'steps':40,'seed':20261015,
            'optimizer':'torch.optim.SGD','head_training_ms':3.,'learning_rate':0.1,
            'fit_train_case_ids_sha256':sha(canonical([r['case_id'] for r in fit['cases']
                 if r['split']=='train' and r['condition']=='original'])),
            'calibration_case_ids_sha256':sha(canonical([r['case_id'] for r in fit['cases']
                 if r['split']=='calibration' and r['condition']=='original'])),
            'train_labels_only_in_gradient':True,
            'initial_frozen_head_sha256':'a'*64,'controls':controls}
    profile=None if is_laya else {'physical_encoder_api_requests':len(fit['cases'])+len(blind['cases']),
                                  'model_load_ms':10.,
                                  'complete_mmbert_weight_bytes_checked':True}
    return {'schema':'hepta.p0.multirc-original-semantic-physical.v1',
        'dataset_schema':SCHEMA,'model':model,'model_revision':REVISIONS[model],
        'panel_id':fit['metadata']['panel_id'],
        'fit_material_sha256':sha(canonical(fit)),
        'blind_material_sha256':sha(canonical(blind)),
        'eval_blind_rows':len(blind['cases']),
        'actual_pretrained_local_weights_claimed':True,
        'physical_model_origin_independently_signed':False,
        'model_selection_permitted':False,'production_promotion_permitted':False,
        'authority':'DENY_ALL','local_process_wall_ms':100.,'local_process_cpu_ms':95.,
        'local_peak_rss_bytes':1_000_000.,'model_load_ms':10.,
        'head_mode':('pretrained_checkpoint_native_noul_nochange_not_equal_head' if is_laya
                     else 'same-initialization-frozen-vs-genuine-human-supervised-sgd'),
        'training':training,'complete_source_profiles':profile,
        'control':controls}


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.train,self.validation,self.fit,self.blind,self.owner=setup()

    def test_complete_and_disjoint(self):
        x,y=validate(self.fit,self.blind)
        self.assertEqual(len(self.owner['original_human_candidate_labels']),COUNTS['test']*2*2)
        self.assertEqual(len(x),2*COUNTS['train']*4+2*COUNTS['calibration']*4)
        self.assertEqual(len(y),2*COUNTS['test']*4)
        self.assertEqual({q['split'] for q in y},{'test'})

    def test_does_not_select_based_on_true_labels(self):
        changed=copy.deepcopy(self.validation)
        for row in changed: row['label']=1-row['label']
        _, blind,owner=build(self.train,changed,train_sha=A,validation_sha=B)
        self.assertEqual(self.blind['cases'],blind['cases'])
        # Calibration labels legitimately alter the sealed panel ID, never selected tasks.
        self.assertNotEqual(self.owner,owner)

    def test_original_human_label_counterfactual_unlabeled(self):
        self.assertTrue(all(r['label'] is None for r in self.fit['cases'] if r['condition']=='no_evidence'))
        self.assertTrue(all('label' not in r for r in self.blind['cases']))

    def test_actual_original_pairs_and_no_evidence(self):
        self.assertTrue(any(r['label']==0 for r in self.fit['cases']))
        self.assertTrue(any(r['label']==1 for r in self.fit['cases']))
        self.assertTrue(all(r['joint_input']['state']=='(no passage evidence available)'
                            for r in self.blind['cases'] if r['condition']=='no_evidence'))

    def test_label_only_changes_train_not_held_material(self):
        train=copy.deepcopy(self.train)
        for row in train: row['label']=1-row['label']
        fit,blind,owner=build(train,self.validation,train_sha=A,validation_sha=B)
        self.assertNotEqual(fit,self.fit)
        self.assertEqual([r['case_id'] for r in blind['cases']],
                         [r['case_id'] for r in self.blind['cases']])

    def test_label_free_selection_complete(self):
        cases=candidates(self.train)
        self.assertEqual(len(cases),17)
        self.assertEqual(sum(len(q['answers']) for q in cases[0]['questions']),4)

    def test_source_order_invariance(self):
        a,b,owner=build(list(reversed(self.train)),list(reversed(self.validation)),
                        train_sha=A,validation_sha=B)
        self.assertEqual((a,b,owner),(self.fit,self.blind,self.owner))

    def test_input_source_identity_sha(self):
        for r in self.blind['cases']:
            self.assertEqual(r['view_sha256'],sha(canonical(r['joint_input'])))

    def test_exact_parent_identity(self):
        self.assertEqual(self.fit['metadata']['schema'],SCHEMA)
        self.assertEqual(self.fit['metadata']['selection_rule'],PROTOCOL)
        self.assertFalse(self.fit['metadata']['production_promotion_permitted'])

    def test_duplicate_answer_rejects(self):
        with self.assertRaises(Invalid): candidates(self.train+[self.train[0]])

    def test_changed_text_same_paragraph_id_rejects(self):
        f=copy.deepcopy(self.train)
        f[1]['paragraph']='unrelated source'
        with self.assertRaises(Invalid): candidates(f)

    def test_bad_label_type_rejects(self):
        f=copy.deepcopy(self.train);f[1]['label']=True
        with self.assertRaises(Invalid): candidates(f)

    def test_bad_parquet_schema_rejects(self):
        f=copy.deepcopy(self.train);f[0]['unexpected']='x'
        with self.assertRaises(Invalid): candidates(f)

    def test_duplicate_source_groups_rejects(self):
        f=copy.deepcopy(self.blind)
        f['cases'][0]['source_group']=self.fit['cases'][0]['source_group']
        with self.assertRaises(Invalid): validate(self.fit,f)

    def test_selfconsistent_forged_view_rejects_independent_source(self):
        fit,blind,owner=copy.deepcopy((self.fit,self.blind,self.owner))
        blind['cases'][0]['joint_input']['state']='Forged replacement source long enough to match a paragraph '
        blind['cases'][0]['view_sha256']=sha(canonical(blind['cases'][0]['joint_input']))
        blind['metadata']['panel_id']='0'*64
        fit['metadata']['panel_id']='0'*64
        with self.assertRaises(Invalid):validate(fit,blind)

    def test_changed_source_label_with_rehashed_receipt_rejected(self):
        forged=copy.deepcopy(self.owner)
        cid=next(iter(forged['original_human_candidate_labels']))
        forged['original_human_candidate_labels'][cid]^=1
        with self.assertRaises(Invalid):
            original_label_audit(self.fit,self.blind,forged,self.train,self.validation)

    def test_forged_model_text_rehashed_caught_at_owner_review(self):
        fit,blind,owner=copy.deepcopy((self.fit,self.blind,self.owner))
        row=blind['cases'][0]
        row['joint_input']['state']=row['joint_input']['state']+' fabricated fact'
        row['view_sha256']=sha(canonical(row['joint_input']))
        meta={k:v for k,v in fit['metadata'].items() if k!='panel_id'}
        h=sha(canonical({'base':meta,'fit':fit['cases'],'blind':blind['cases']}))
        fit['metadata']['panel_id']=blind['metadata']['panel_id']=owner['panel_id']=h
        with self.assertRaises(Invalid):
            original_label_audit(fit,blind,owner,self.train,self.validation)

    def test_incomplete_paired_intervention_rejects(self):
        b=copy.deepcopy(self.blind);b['cases'].pop()
        with self.assertRaises(Invalid):validate(self.fit,b)

    def test_no_evidence_fake_human_label_rejects(self):
        f=copy.deepcopy(self.fit)
        r=next(x for x in f['cases'] if x['condition']=='no_evidence')
        r['label']=0
        with self.assertRaises(Invalid):validate(f,self.blind)

    def test_training_label_leak_to_blind_rejects(self):
        b=copy.deepcopy(self.blind);b['cases'][0]['label']=1
        with self.assertRaises(Invalid):validate(self.fit,b)

    def test_same_condition_duplicate_rejects(self):
        b=copy.deepcopy(self.blind);b['cases'].append(copy.deepcopy(b['cases'][0]))
        with self.assertRaises(Invalid):validate(self.fit,b)

    def test_scope_authority_fails_closed(self):
        b=copy.deepcopy(self.blind);b['metadata']['production_promotion_permitted']=True
        with self.assertRaises(Invalid):validate(self.fit,b)

    def test_sha_validation(self):
        with self.assertRaises(Invalid):checked_source_hash('f'*63)
        with self.assertRaises(Invalid):checked_source_hash('0'*63+'Z')

    def test_duplicate_json_keys_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'bad.json';p.write_text('{"a":1,"a":2}')
            with self.assertRaises(Invalid):read(p)

    def test_create_only_receipt(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'source.json'
            save(p,{'a':2})
            with self.assertRaises(FileExistsError):save(p,{'a':3})

    def test_no_future_benefit_is_always_declared_false(self):
        self.assertIs(self.fit['metadata']['temporal_future_windows_verified'],False)


class EfficacyReviewTests(unittest.TestCase):
    def setUp(self):
        self.train,self.validation,self.fit,self.blind,self.owner=setup()
        self.reports={m:mocked_report(m,self.fit,self.blind) for m in REQUIRED}

    def test_full_replay_and_literal_hardness(self):
        out=review(self.fit,self.blind,self.owner,self.train,self.validation,self.reports)
        self.assertEqual(out['original_human_answer_rows'],32)
        self.assertEqual(out['original_human_exact_lexical_hard_rows'],32)
        self.assertEqual(out['cheap_exact_literal_presence_baseline']['accuracy'],.5)
        self.assertFalse(out['model_winner_selected'])

    def test_hard_positive_negative_pair(self):
        out=review(self.fit,self.blind,self.owner,self.train,self.validation,self.reports)
        self.assertGreater(out['same_answer_text_with_opposite_original_labels'],0)
        self.assertGreater(out['models']['mmbert_small']['arms']['trained_head']['hard_question_count'],0)

    def test_unlabeled_no_evidence_has_no_brier(self):
        out=review(self.fit,self.blind,self.owner,self.train,self.validation,self.reports)
        self.assertFalse(out['artificially_transformed_evidence_has_human_label'])
        self.assertAlmostEqual(out['models']['granite_97m_r2']['arms']['frozen_head']['original_minus_no_evidence_mean_probability_shift'],.02)

    def test_no_evidence_is_original_target_prior_not_invented_label(self):
        out=review(self.fit,self.blind,self.owner,self.train,self.validation,self.reports)
        self.assertEqual(out['schema'],'hepta.p0.multirc-original-semantic-independent-review.v2')
        d=out['models']['granite_97m_r2']['arms']['trained_head']['evidence_vs_priors_original_target_only']
        self.assertEqual(d['target'],'original_human_label_only_not_no_evidence_entailment')
        self.assertEqual(d['per_source_brier_gain_count'],COUNTS['test'])
        self.assertEqual(d['no_evidence_prior_predictor_against_original_labels']['rows'],32)
        self.assertFalse(d['causal_semantic_superiority_proven'])
        self.assertFalse(out['no_evidence_has_new_human_ground_truth'])

    def test_evidence_zero_delta_still_inconclusive(self):
        d=copy.deepcopy(self.reports)
        for r in d['granite_97m_r2']['control']['trained_head']['predictions']:
            r['positive_probability']=.5
        out=review(self.fit,self.blind,self.owner,self.train,self.validation,d)
        x=out['models']['granite_97m_r2']['arms']['trained_head']['evidence_vs_priors_original_target_only']
        self.assertEqual(x['mean_paired_brier_gain_positive_is_better'],0)
        self.assertEqual(x['source_groups_improved'],0)
        self.assertEqual(x['source_groups_harmed'],0)

    def test_negative_evidence_gain_not_filtered(self):
        d=copy.deepcopy(self.reports)
        rows={r['case_id']:r for r in self.blind['cases']}
        for item in d['mmbert_small']['control']['trained_head']['predictions']:
            r=rows[item['case_id']]
            if r['condition']=='original':
                item['positive_probability']=.95 if self.owner['original_human_candidate_labels'][item['case_id']]==0 else .05
            else:
                item['positive_probability']=.5
        out=review(self.fit,self.blind,self.owner,self.train,self.validation,d)
        x=out['models']['mmbert_small']['arms']['trained_head']['evidence_vs_priors_original_target_only']
        self.assertLess(x['mean_paired_brier_gain_positive_is_better'],0)
        self.assertEqual(x['source_groups_harmed'],COUNTS['test'])
        self.assertFalse(x['causal_semantic_superiority_proven'])

    def test_source_train_id_wrong_with_rehashed_claim_rejects(self):
        d=copy.deepcopy(self.reports)
        d['granite_97m_r2']['training']['fit_train_case_ids_sha256']='c'*64
        with self.assertRaises(Invalid):review(self.fit,self.blind,self.owner,self.train,self.validation,d)

    def test_calibration_provenance_wrong_rejects(self):
        d=copy.deepcopy(self.reports)
        d['mmbert_small']['training']['calibration_case_ids_sha256']='d'*64
        with self.assertRaises(Invalid):review(self.fit,self.blind,self.owner,self.train,self.validation,d)

    def test_false_train_only_gradient_receipt_rejects(self):
        d=copy.deepcopy(self.reports)
        d['embeddinggemma_2_text']['training']['train_labels_only_in_gradient']=False
        with self.assertRaises(Invalid):review(self.fit,self.blind,self.owner,self.train,self.validation,d)

    def test_frozen_initial_tensor_lineage_wrong_rejects(self):
        d=copy.deepcopy(self.reports)
        d['granite_97m_r2']['training']['initial_frozen_head_sha256']='e'*64
        with self.assertRaises(Invalid):review(self.fit,self.blind,self.owner,self.train,self.validation,d)

    def test_cloned_unchanged_trained_head_rejects(self):
        d=copy.deepcopy(self.reports)
        d['mmbert_small']['control']['trained_head']['head_sha256']='a'*64
        with self.assertRaises(Invalid):review(self.fit,self.blind,self.owner,self.train,self.validation,d)

    def test_report_training_controls_drift_rejects(self):
        d=copy.deepcopy(self.reports)
        d['granite_97m_r2']['training']['controls']=copy.deepcopy(d['granite_97m_r2']['control'])
        d['granite_97m_r2']['control']['trained_head']['predictions'][0]['positive_probability']=0.1
        with self.assertRaises(Invalid):review(self.fit,self.blind,self.owner,self.train,self.validation,d)

    def test_paid_request_sum_exceeds_process_time_rejects(self):
        d=copy.deepcopy(self.reports)
        for item in d['laya421_nochange']['control']['laya_native_nochange']['predictions']:
            item['full_request_ms']=4.0
        with self.assertRaises(Invalid):review(self.fit,self.blind,self.owner,self.train,self.validation,d)

    def test_head_lr_drift_rejects(self):
        d=copy.deepcopy(self.reports)
        d['granite_97m_r2']['training']['learning_rate']=.11
        with self.assertRaises(Invalid):review(self.fit,self.blind,self.owner,self.train,self.validation,d)

    def test_real_torch_head_lineage_fields_equal_to_physical_receipt(self):
        import torch
        train,val,fit,blind,owner=setup()
        gen=torch.Generator().manual_seed(109)
        x={r['case_id']:torch.randn(384,generator=gen).tolist()
           for r in fit['cases']+blind['cases']}
        actual=fit_head(fit['cases'],blind['cases'],x,384)
        self.assertEqual(actual['initial_frozen_head_sha256'],actual['controls']['frozen_head']['head_sha256'])
        self.assertNotEqual(actual['initial_frozen_head_sha256'],actual['controls']['trained_head']['head_sha256'])
        self.assertEqual(actual['fit_train_case_ids_sha256'],sha(canonical([r['case_id'] for r in fit['cases']
                         if r['split']=='train' and r['condition']=='original'])))
        self.assertEqual(actual['calibration_case_ids_sha256'],sha(canonical([r['case_id'] for r in fit['cases']
                         if r['split']=='calibration' and r['condition']=='original'])))

    def test_missing_model_fails(self):
        d=copy.deepcopy(self.reports);d.pop('laya421_nochange')
        with self.assertRaises(Invalid):review(self.fit,self.blind,self.owner,self.train,self.validation,d)

    def test_alias_models_fails(self):
        d=copy.deepcopy(self.reports);d['granite_97m_r2']=d['mmbert_small']
        with self.assertRaises(Invalid):review(self.fit,self.blind,self.owner,self.train,self.validation,d)

    def test_claim_false_future_fails(self):
        d=copy.deepcopy(self.reports);d['mmbert_small']['authority']='ALLOW_ALL'
        with self.assertRaises(Invalid):review(self.fit,self.blind,self.owner,self.train,self.validation,d)

    def test_duplicate_prediction_fails(self):
        d=copy.deepcopy(self.reports)
        v=d['granite_97m_r2']['control']['trained_head']['predictions']
        v[1]['case_id']=v[0]['case_id']
        with self.assertRaises(Invalid):review(self.fit,self.blind,self.owner,self.train,self.validation,d)

    def test_missing_prediction_fails(self):
        d=copy.deepcopy(self.reports);d['granite_97m_r2']['control']['trained_head']['predictions'].pop()
        with self.assertRaises(Invalid):review(self.fit,self.blind,self.owner,self.train,self.validation,d)

    def test_rehashed_swapped_prediction_view_fails(self):
        d=copy.deepcopy(self.reports);d['granite_97m_r2']['control']['trained_head']['predictions'][0]['view_sha256']='e'*64
        with self.assertRaises(Invalid):review(self.fit,self.blind,self.owner,self.train,self.validation,d)

    def test_resource_malformed_fails(self):
        d=copy.deepcopy(self.reports);d['granite_97m_r2']['local_process_wall_ms']=float('nan')
        with self.assertRaises(Invalid):review(self.fit,self.blind,self.owner,self.train,self.validation,d)

    def test_optimizer_budget_mismatch_fails(self):
        d=copy.deepcopy(self.reports);d['mmbert_small']['training']['steps']=39
        with self.assertRaises(Invalid):review(self.fit,self.blind,self.owner,self.train,self.validation,d)

    def test_immutable_mmbert_weight_required(self):
        d=copy.deepcopy(self.reports);d['mmbert_small']['complete_source_profiles']['complete_mmbert_weight_bytes_checked']=False
        with self.assertRaises(Invalid):review(self.fit,self.blind,self.owner,self.train,self.validation,d)

    def test_laya_cannot_masquerade_equal_head(self):
        d=copy.deepcopy(self.reports);d['laya421_nochange']['training']={'steps':40}
        with self.assertRaises(Invalid):review(self.fit,self.blind,self.owner,self.train,self.validation,d)

    def test_impossible_lifecycle_fails(self):
        d=copy.deepcopy(self.reports);d['mmbert_small']['local_process_wall_ms']=1.
        with self.assertRaises(Invalid):review(self.fit,self.blind,self.owner,self.train,self.validation,d)

    def test_simple_metrics(self):
        self.assertEqual(metrics([(.6,1),(.2,0)])['accuracy'],1.0)
        self.assertAlmostEqual(metrics([(.6,1),(.2,0)])['brier'],.1)
        with self.assertRaises(Invalid):numeric(True)


class ActualTorchHeadTests(unittest.TestCase):
    def test_synthetic_tensor_actual_sgd_and_dormant_frozen(self):
        import torch
        train,val,fit,blind,owner=setup()
        generator=torch.Generator().manual_seed(81)
        features={r['case_id']:torch.randn(384,generator=generator).tolist()
                  for r in fit['cases']+blind['cases']}
        observed=fit_head(fit['cases'],blind['cases'],features,384)
        self.assertEqual(observed['parameter_count'],770)
        self.assertNotEqual(observed['controls']['trained_head']['head_sha256'],
                            observed['controls']['frozen_head']['head_sha256'])
        self.assertEqual(len(observed['controls']['trained_head']['predictions']),len(blind['cases']))


if __name__=='__main__':unittest.main()
