"""Offline fake-feature controls, real Torch SGD, and adversarial human-label audits.

Every feature tensor in this test module is explicitly SYNTHETIC. Passing it
cannot certify pretrained Stem usefulness, human independent review or release.
"""
from __future__ import annotations
import copy
import math
import random
import sys
import types
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from p0_multirc_semantic_material import Invalid, canonical, sha, build
from p0_multirc_semantic_execute import fit_head, run
from p0_multirc_semantic_review import REQUIRED,REVISIONS
from p0_question_only_head import fit_question_only,matched_pairs,SCHEMA
from p0_question_only_review import review,OUT_SCHEMA
from test_p0_multirc_semantic import setup,mocked_report


def fake_vectors(rows, width):
    def make(id):
        rng=random.Random(int(id,16))
        return [rng.uniform(-0.35,0.35) for _ in range(width)]
    return {row['case_id']:make(row['case_id']) for row in rows}


def match_fixture(fit,blind,model):
    reports={m:mocked_report(m,fit,blind) for m in REQUIRED}
    train=[r['case_id'] for r in fit['cases'] if r['split']=='train' and r['condition']=='original']
    cal=[r['case_id'] for r in fit['cases'] if r['split']=='calibration' and r['condition']=='original']
    combined={r['case_id'] for r in fit['cases']+blind['cases']}
    for m in REQUIRED[:-1]:
        p=reports[m]; width=384 if m!='embeddinggemma_2_text' else 256
        pp=matched_pairs(fit,blind)
        fi={r['case_id']:i for i,r in enumerate(fit['cases'])}
        t=sorted(pp['train'],key=lambda a:fi[a[0]['case_id']]);c=sorted(pp['calibration'],key=lambda a:fi[a[0]['case_id']])
        ctl={}
        for mode,hash_ in [('question_frozen_head','a'*64),('question_trained_head','c'*64)]:
            ctl[mode]={'head_sha256':hash_, 'temperature':1.,'predictions':[
                {'original_case_id':o['case_id'],'no_evidence_case_id':q['case_id'],
                 'no_evidence_view_sha256':q['view_sha256'],
                 'positive_probability':.5 if mode=='question_frozen_head' else .53,
                 'head_request_ms':.04} for o,q in pp['test']]}
        p['matched_question_only_control']={
            'schema':SCHEMA, 'target':'original_human_binary_label_predicted_without_passage_evidence',
            'no_evidence_material_has_new_human_ground_truth':False,
            'source_training_only':True,
            'per_head_trainable_parameters':2*width+2,
            'optimizer':'torch.optim.SGD','steps':40,'seed':20261015,'learning_rate':0.1,
            'train_source_case_ids_sha256':sha(canonical(train)),
            'calibration_source_case_ids_sha256':sha(canonical(cal)),
            'train_question_case_ids_sha256':sha(canonical([q['case_id'] for o,q in t])),
            'calibration_question_case_ids_sha256':sha(canonical([q['case_id'] for o,q in c])),
            'matched_train_example_count':len(t),'matched_calibration_example_count':len(c),
            'original_and_prior_initial_tensor_sha256':'a'*64,
            'question_only_head_training_ms':3.0,
            'reuse_same_original_shared_encoder_load':True,
            'additional_model_loads':0,'additional_encoder_forwards':0,
            'complete_prior_controls':ctl,'production_promotion_permitted':False,'authority':'DENY_ALL'}
        p['complete_source_profiles']['physical_encoder_ms_by_case']={key:.001 for key in combined}
    return reports


class MatchedTrainingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source_train,cls.source_validation,cls.fit,cls.blind,cls.owner=setup()

    def test_pair_complete_without_invented_labels(self):
        pairs=matched_pairs(self.fit,self.blind)
        self.assertEqual(len(pairs['train']),48)
        self.assertEqual(len(pairs['calibration']),16)
        self.assertEqual(len(pairs['test']),32)
        self.assertTrue(all(q['label'] is None for s in ('train','calibration') for o,q in pairs[s]))
        self.assertTrue(all('label' not in o and 'label' not in q for o,q in pairs['test']))

    def _trained(self,width=384):
        rows=self.fit['cases']+self.blind['cases']
        v=fake_vectors(rows,width)
        parent=fit_head(self.fit['cases'],self.blind['cases'],v,width)
        q=fit_question_only(self.fit,self.blind,v,width,parent)
        return parent,q,v

    def test_real_torch_sgd_384(self):
        parent,c,v=self._trained(384)
        self.assertEqual(c['per_head_trainable_parameters'],770)
        self.assertEqual(c['steps'],parent['steps'])
        self.assertEqual(c['original_and_prior_initial_tensor_sha256'],parent['initial_frozen_head_sha256'])
        self.assertNotEqual(c['complete_prior_controls']['question_trained_head']['head_sha256'],parent['initial_frozen_head_sha256'])
        self.assertEqual(len(c['complete_prior_controls']['question_trained_head']['predictions']),len(self.blind['cases'])//2)
        self.assertEqual(c['additional_encoder_forwards'],0)
        self.assertIs(c['no_evidence_material_has_new_human_ground_truth'],False)

    def test_real_torch_sgd_256(self):
        _,p,_=self._trained(256)
        self.assertEqual(p['per_head_trainable_parameters'],514)

    def test_stable_seed_replay(self):
        a=self._trained(256)[1]
        b=self._trained(256)[1]
        self.assertEqual(a['complete_prior_controls']['question_trained_head']['head_sha256'],
                         b['complete_prior_controls']['question_trained_head']['head_sha256'])
        self.assertEqual([x['positive_probability'] for x in a['complete_prior_controls']['question_trained_head']['predictions']],
                         [x['positive_probability'] for x in b['complete_prior_controls']['question_trained_head']['predictions']])

    def test_fit_labels_change_trained_head_but_not_frozen_head(self):
        original=self._trained(256)[1]
        fit=copy.deepcopy(self.fit)
        for r in fit['cases']:
            if r['split']=='train' and r['condition']=='original':r['label']=1-r['label']
        meta=fit['metadata']; meta['panel_id']=sha(canonical({'base':{k:v for k,v in meta.items() if k!='panel_id'},
                                               'fit':fit['cases'],'blind':self.blind['cases']}))
        blind=copy.deepcopy(self.blind);blind['metadata']=copy.deepcopy(meta)
        v=fake_vectors(fit['cases']+blind['cases'],256)
        parent=fit_head(fit['cases'],blind['cases'],v,256)
        changed=fit_question_only(fit,blind,v,256,parent)
        self.assertEqual(changed['original_and_prior_initial_tensor_sha256'],original['original_and_prior_initial_tensor_sha256'])
        self.assertNotEqual(changed['complete_prior_controls']['question_trained_head']['head_sha256'],original['complete_prior_controls']['question_trained_head']['head_sha256'])

    def test_refuses_wrong_evidence_initial(self):
        parent,q,v=self._trained(256);parent['initial_frozen_head_sha256']='d'*64
        with self.assertRaises(Invalid):fit_question_only(self.fit,self.blind,v,256,parent)

    def test_refuses_changed_parent_training_source(self):
        parent,q,v=self._trained(256);parent['fit_train_case_ids_sha256']='d'*64
        with self.assertRaises(Invalid):fit_question_only(self.fit,self.blind,v,256,parent)

    def test_refuses_wrong_optimizer(self):
        parent,q,v=self._trained(256);parent['steps']=39
        with self.assertRaises(Invalid):fit_question_only(self.fit,self.blind,v,256,parent)

    def test_refuses_missing_feature(self):
        parent,q,v=self._trained(256);v.pop(next(iter(v)))
        with self.assertRaises(Invalid):fit_question_only(self.fit,self.blind,v,256,parent)

    def test_refuses_nan_feature(self):
        parent,q,v=self._trained(256);v[next(iter(v))][0]=float('nan')
        with self.assertRaises(Invalid):fit_question_only(self.fit,self.blind,v,256,parent)

    def test_refuses_feature_outside_registered_range(self):
        parent,q,v=self._trained(256);v[next(iter(v))][0]=1000.
        with self.assertRaises(Invalid):fit_question_only(self.fit,self.blind,v,256,parent)

    def test_refuses_forged_no_evidence_human_label(self):
        fit=copy.deepcopy(self.fit)
        next(x for x in fit['cases'] if x['condition']=='no_evidence')['label']=0
        with self.assertRaises(Invalid):matched_pairs(fit,self.blind)

    def test_refuses_heldout_label_added(self):
        blind=copy.deepcopy(self.blind);blind['cases'][0]['label']=1
        with self.assertRaises(Invalid):matched_pairs(self.fit,blind)

    def test_real_executor_reuses_model_forward_and_runs_both_heads(self):
        # A fake Encoder is explicitly a source-only control; its predictions
        # cannot establish actual pretrained weights or scientific efficacy.
        rows=self.fit['cases']+self.blind['cases']
        bank=fake_vectors(rows,256)
        calls=[]
        def fake_encode(cases,model,a,b,c):
            calls.append((model,len(cases)))
            return bank,{r['case_id']:12 for r in cases},{r['case_id']:'a'*64 for r in cases}, {
                'local_model_api_requests':len(cases),'load_ms':10.,
                'encode_ms_by_case':{r['case_id']:.001 for r in cases}}
        fake_module=types.ModuleType('e1_public_triplet_real_cpu')
        fake_module.encode_pretrained=fake_encode
        ns=SimpleNamespace(compact_checkout='provided',gemma_checkout='provided',gemma_manifest='given')
        with patch.dict(sys.modules,{'e1_public_triplet_real_cpu':fake_module}):
            result=run(self.fit,self.blind,'embeddinggemma_2_text',ns)
        self.assertEqual(calls,[('embeddinggemma_2_text',len(rows))])
        self.assertEqual(result['matched_question_only_control']['per_head_trainable_parameters'],514)
        self.assertEqual(result['matched_question_only_control']['additional_model_loads'],0)
        self.assertEqual(result['complete_source_profiles']['physical_encoder_ms_by_case'],
                         {r['case_id']:.001 for r in rows})
        self.assertFalse(result['production_promotion_permitted'])


class MatchedReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source_train,cls.source_validation,cls.fit,cls.blind,cls.owner=setup()

    def setUp(self):
        self.reports=match_fixture(self.fit,self.blind,'all')

    def score(self,reports=None):
        return review(self.fit,self.blind,self.owner,self.source_train,self.source_validation,
                      self.reports if reports is None else reports)

    def test_original_human_v2_unchanged_and_new_matched_scores(self):
        a=self.score()
        self.assertEqual(a['schema'],OUT_SCHEMA)
        self.assertEqual(a['original_human_scorer_v2']['schema'],
                         'hepta.p0.multirc-original-semantic-independent-review.v2')
        self.assertEqual(a['original_human_label_cases'],32)
        self.assertEqual(a['matched_models']['granite_97m_r2']['learned_evidence_versus_separately_trained_question_only']['source_passages'],8)
        self.assertTrue(a['equal_train_budget_is_not_equal_encoder_input_work'])
        self.assertFalse(a['stem_or_model_selection_permitted'])
        self.assertFalse(a['no_evidence_view_human_entailment_label_invented'])

    def mutate(self,change):
        a=copy.deepcopy(self.reports);change(a)
        with self.assertRaises(Invalid):self.score(a)

    def test_missing_model_fails(self):
        self.mutate(lambda a:a.pop('mmbert_small'))

    def test_laya_not_equal_head_fails(self):
        self.mutate(lambda a:a['laya421_nochange'].update(matched_question_only_control={}))

    def test_missing_question_only_fails(self):
        self.mutate(lambda a:a['granite_97m_r2'].pop('matched_question_only_control'))

    def test_rejects_forged_no_evidence_truth_flag(self):
        self.mutate(lambda a:a['granite_97m_r2']['matched_question_only_control'].update(no_evidence_material_has_new_human_ground_truth=True))

    def test_wrong_trained_head_params(self):
        self.mutate(lambda a:a['embeddinggemma_2_text']['matched_question_only_control'].update(per_head_trainable_parameters=900))

    def test_wrong_optimizer_steps(self):
        self.mutate(lambda a:a['mmbert_small']['matched_question_only_control'].update(steps=41))

    def test_wrong_original_train_digest(self):
        self.mutate(lambda a:a['mmbert_small']['matched_question_only_control'].update(train_source_case_ids_sha256='0'*64))

    def test_wrong_prior_train_digest(self):
        self.mutate(lambda a:a['mmbert_small']['matched_question_only_control'].update(train_question_case_ids_sha256='0'*64))

    def test_wrong_calibration_digest(self):
        self.mutate(lambda a:a['mmbert_small']['matched_question_only_control'].update(calibration_question_case_ids_sha256='0'*64))

    def test_initial_tensor_mismatch(self):
        self.mutate(lambda a:a['granite_97m_r2']['matched_question_only_control'].update(original_and_prior_initial_tensor_sha256='e'*64))

    def test_false_no_sgd_update(self):
        self.mutate(lambda a:a['granite_97m_r2']['matched_question_only_control']['complete_prior_controls']['question_trained_head'].update(head_sha256='a'*64))

    def test_missing_prior_prediction(self):
        self.mutate(lambda a:a['granite_97m_r2']['matched_question_only_control']['complete_prior_controls']['question_trained_head']['predictions'].pop())

    def test_wrong_original_task_link(self):
        self.mutate(lambda a:a['mmbert_small']['matched_question_only_control']['complete_prior_controls']['question_trained_head']['predictions'][0].update(original_case_id='f'*32))

    def test_duplicate_prior_prediction(self):
        self.mutate(lambda a:a['mmbert_small']['matched_question_only_control']['complete_prior_controls']['question_trained_head']['predictions'][1].update(no_evidence_case_id=a['mmbert_small']['matched_question_only_control']['complete_prior_controls']['question_trained_head']['predictions'][0]['no_evidence_case_id']))

    def test_wrong_prior_view_digest(self):
        self.mutate(lambda a:a['mmbert_small']['matched_question_only_control']['complete_prior_controls']['question_trained_head']['predictions'][0].update(no_evidence_view_sha256='a'*64))

    def test_missing_cost_profile(self):
        self.mutate(lambda a:a['granite_97m_r2']['complete_source_profiles'].pop('physical_encoder_ms_by_case'))

    def test_missing_one_real_encoder_forward(self):
        self.mutate(lambda a:a['granite_97m_r2']['complete_source_profiles']['physical_encoder_ms_by_case'].pop(next(iter(a['granite_97m_r2']['complete_source_profiles']['physical_encoder_ms_by_case']))))

    def test_forged_extra_encoder_load(self):
        self.mutate(lambda a:a['granite_97m_r2']['matched_question_only_control'].update(additional_model_loads=1))

    def test_nonzero_prior_model_forward_fails(self):
        self.mutate(lambda a:a['granite_97m_r2']['matched_question_only_control'].update(additional_encoder_forwards=1))

    def test_made_up_wall_time_fails(self):
        self.mutate(lambda a:a['granite_97m_r2'].update(local_process_wall_ms=.01))

    def test_unreal_head_request_fails(self):
        self.mutate(lambda a:a['granite_97m_r2']['matched_question_only_control']['complete_prior_controls']['question_trained_head']['predictions'][0].update(head_request_ms=10000))

    def test_inf_probability_fails(self):
        self.mutate(lambda a:a['granite_97m_r2']['matched_question_only_control']['complete_prior_controls']['question_trained_head']['predictions'][0].update(positive_probability=float('inf')))

    def test_negative_prior_gain_is_preserved(self):
        o=self.score()['matched_models']['granite_97m_r2']['learned_evidence_versus_separately_trained_question_only']
        self.assertEqual(o['groups_evidence_better']+o['groups_question_only_better']+o['groups_tied'],8)
        self.assertFalse(o['independent_large_sample_causal_advantage'])

    def test_manual_owner_label_change_rejected(self):
        a=copy.deepcopy(self.owner)
        k=next(iter(a['original_human_candidate_labels']))
        a['original_human_candidate_labels'][k]^=1
        with self.assertRaises(Invalid): review(self.fit,self.blind,a,self.source_train,self.source_validation,self.reports)

    def test_original_score_cost_and_prior_cost_kept_separate(self):
        r=self.score()
        x=r['matched_models']['mmbert_small']
        self.assertGreater(x['metered_encoder_ms_all_views_once'],0)
        self.assertGreater(x['metered_evidence_train_ms'],0)
        self.assertGreater(x['metered_prior_train_ms'],0)
        self.assertGreater(x['metered_head_inference_ms_evidence_and_prior'],0)


if __name__=='__main__': unittest.main()
