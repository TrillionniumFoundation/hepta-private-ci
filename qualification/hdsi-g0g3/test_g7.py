"""Source-only adversarial contracts; optional original Model/LoCoMo evidence check."""
from __future__ import annotations

import copy
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from g6_coverage_source import SCHEMA as G6_SCHEMA, DOMAIN as G6_DOMAIN, TRAIN, HELD, canonical, sha,validate
from real_minilm_reference import CHECKSUMS
from g7_policy import ACTIONS,BANDS,freeze_train,feature_band,expected_value,ndu_backward,bellman_forward,plan,verify_plan,verify_profile,hash_object
from g7_train import rrf_ranking
from g7_review import independent_dp,clean_json,independently_score


def synthetic_public():
    roots=[]
    for name in sorted(TRAIN+HELD):
        training=name in TRAIN
        docs=[{'id':f'D1:{i}','text':f'Alice discussed project {i} details for {name}',
               'text_sha':sha(f'Alice discussed project {i} details for {name}'.encode())}
              for i in range(256 if training else 300)]
        qs=[]
        for i in range(24):
            text=f'Which project {i} did Alice discuss in {name}?'
            q={'id':f'q{i}','text':text,'text_sha':sha(text.encode())}
            if training:q['train_support']=[f'D1:{i}']
            qs.append(q)
        roots.append({'root':name,'split':'TRAIN' if training else 'HELD',
                      'docs':docs,'questions':qs})
    p={'schema':G6_SCHEMA,'original_sha':CHECKSUMS['locomo.json'],
       'model_sha':CHECKSUMS['encoder/model.safetensors'],
       'original_g5_packet_digest':'a'*64,'train_documents_per_root':256,
       'candidate_documents':'all_held_original_dialogues','questions_per_root':24,
       'rerank_shortlist':64,'roots':roots,'research_only':True,
       'production_authorized':False,'disposition':'HOLD_NO_GO'}
    p['digest']=sha(G6_DOMAIN+canonical(p))
    validate(p)
    return p


def training(public):
    return [{'root':r['root'],'qid':q['id'],'source_sha':q['text_sha'],
             'band':('weak','medium','strong')[i%3],
             'bm25_hit':i%3==0,'rrf_hit':i%2==0}
            for r in public['roots'] if r['split']=='TRAIN' for i,q in enumerate(r['questions'])]


def held(public):
    return sorted([{'root':r['root'],'qid':q['id'],'source_sha':q['text_sha'],
                    'band':('weak','medium','strong')[i%3],
                    'bm25_top5_ids':[d['id'] for d in r['docs'][:5]]}
                   for r in public['roots'] if r['split']=='HELD' for i,q in enumerate(r['questions'])],
                  key=lambda x:(x['root'],x['qid']))


class G7SourceOnlyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=synthetic_public()
        cls.data=training(cls.source)
        cls.profile=freeze_train(cls.source,cls.data)
        cls.routes=held(cls.source)
        cls.plan=plan(cls.source,cls.profile,cls.routes)

    def test_01_exact_original_group_partition_is_source_bound(self):
        self.assertEqual(len(self.source['roots']),10)
        self.assertEqual(len(self.data),144)
        self.assertEqual(len(self.plan['decisions']),96)

    def test_02_train_profile_disallows_unknown_field(self):
        altered=copy.deepcopy(self.data);altered[0]['oracle_correct']=True
        with self.assertRaises(ValueError):freeze_train(self.source,altered)

    def test_03_duplicate_training_event_fails(self):
        altered=copy.deepcopy(self.data);altered[1]=altered[0]
        with self.assertRaises(ValueError):freeze_train(self.source,altered)

    def test_04_cross_source_held_gold_poison_fails(self):
        poisoned=copy.deepcopy(self.source)
        next(r for r in poisoned['roots'] if r['split']=='HELD')['questions'][0]['gold_evidence']=['D1:4']
        poisoned['digest']=sha(G6_DOMAIN+canonical({k:v for k,v in poisoned.items() if k!='digest'}))
        with self.assertRaises(ValueError):freeze_train(poisoned,self.data)

    def test_05_trained_head_not_imported_into_pure_policy(self):
        self.assertNotIn('torch',sys.modules)
        self.assertEqual(self.profile['smoothing'],'beta_1_1')

    def test_06_float_lookalike_parameter_is_not_int(self):
        with self.assertRaises(ValueError):ndu_backward(self.profile,['strong'],8.0)

    def test_07_negative_budget_rejected(self):
        with self.assertRaises(ValueError):bellman_forward(self.profile,['weak'],-1)

    def test_08_finite_horizon_bound(self):
        with self.assertRaises(ValueError):ndu_backward(self.profile,['strong']*25,8)

    def test_09_same_utility_parity_on_all_lengths(self):
        for n in range(1,25):
            values=[BANDS[(i*17+n)%3] for i in range(n)]
            for cap in range(0,9):
                self.assertEqual(ndu_backward(self.profile,values,cap),
                                 bellman_forward(self.profile,values,cap))

    def test_10_independent_forward_parity(self):
        x=['weak','strong','medium','strong']
        answer=tuple(ACTIONS[i] for i in ndu_backward(self.profile,x,2))
        self.assertEqual(independent_dp(self.profile,x,2),answer)

    def test_11_no_cost_doubled_between_stop_and_common_BM25(self):
        self.assertEqual(expected_value(self.profile,'strong',0),Fraction(0))
        self.assertEqual(self.profile['utility']['bm25_common_scan_fee_excluded_from_action_difference'],True)

    def test_12_unavailable_band_cannot_fabricate_action(self):
        with self.assertRaises(ValueError):expected_value(self.profile,'absent',1)

    def test_13_stop_and_submit_have_distinct_reward(self):
        self.assertNotEqual(expected_value(self.profile,'medium',0),expected_value(self.profile,'medium',1))

    def test_14_frozen_source_request_mismatch_denied(self):
        altered=copy.deepcopy(self.routes);altered[0]['source_sha']='0'*64
        with self.assertRaises(ValueError):plan(self.source,self.profile,altered)

    def test_15_frozen_order_guard(self):
        altered=copy.deepcopy(self.routes);altered[0],altered[1]=altered[1],altered[0]
        with self.assertRaises(ValueError):plan(self.source,self.profile,altered)

    def test_16_forged_held_label_key_refused(self):
        altered=copy.deepcopy(self.routes);altered[0]['held_answer']='surprise'
        with self.assertRaises(ValueError):plan(self.source,self.profile,altered)

    def test_17_changed_model_identity_denied_even_after_reseal(self):
        altered=copy.deepcopy(self.profile);altered['model_sha']='a'*64
        altered['digest']=hash_object({k:v for k,v in altered.items() if k!='digest'})
        with self.assertRaises(ValueError):verify_profile(altered,self.source)

    def test_18_wrong_budget_cannot_reinterpret_plan(self):
        altered=copy.deepcopy(self.plan);altered['cap_per_root']=7
        altered['digest']=hash_object({k:v for k,v in altered.items() if k!='digest'})
        with self.assertRaises(ValueError):verify_plan(self.source,self.profile,altered)

    def test_19_overriding_selected_action_postseal_rejected(self):
        altered=copy.deepcopy(self.plan);altered['decisions'][0]['ndu']='RERANK'
        altered['digest']=hash_object({k:v for k,v in altered.items() if k!='digest'})
        with self.assertRaises(ValueError):verify_plan(self.source,self.profile,altered)

    def test_20_top5_complete_source_roster_required(self):
        altered=copy.deepcopy(self.routes);altered[0]['bm25_top5_ids']=['D1:1']*5
        with self.assertRaises(ValueError):plan(self.source,self.profile,altered)

    def test_21_lexical_feature_is_source_only(self):
        self.assertEqual(feature_band('hello black cat','cat'), 'medium')
        self.assertEqual(feature_band('unique krill','entirely distinct words'), 'weak')
        self.assertEqual(feature_band('the quick fox','the quick fox'), 'strong')

    def test_22_rrf_whole_tail_stays_in_old_order(self):
        seq=list(range(70));sem=[float(i) for i in range(64)]
        combined=rrf_ranking(seq,sem)
        self.assertEqual(set(combined[:64]),set(seq[:64]))
        self.assertEqual(combined[64:],seq[64:])

    def test_23_invalid_nn_nonfinite_rejected_before_publish(self):
        with self.assertRaises(ValueError):rrf_ranking(list(range(70)),[0.]*63+[float('nan')])

    def test_24_group_discount_is_not_silent(self):
        self.assertEqual(self.profile['utility']['rerank_incremental_fee'],900)
        self.assertFalse(self.plan['precommitted_original_future'])

    def test_25_no_selected_current_run_effect(self):
        self.assertFalse(self.plan['production_authorized'])
        self.assertEqual(self.plan['disposition'],'HOLD_NO_GO')

    def test_26_greedy_not_claimed_as_exact_planner(self):
        out=ndu_backward(self.profile,['weak','strong','medium','weak'],1)
        self.assertEqual(out,bellman_forward(self.profile,['weak','strong','medium','weak'],1))

    def test_27_no_nested_unknown_plan_fields(self):
        altered=copy.deepcopy(self.plan);altered['new_authority']=True
        altered['digest']=hash_object({k:v for k,v in altered.items() if k!='digest'})
        with self.assertRaises(ValueError):verify_plan(self.source,self.profile,altered)

    def test_28_independent_config_ints(self):
        self.assertEqual(self.profile['max_paid_questions_per_root'],8)
        self.assertTrue(all(int(x['fixed']=='RERANK') in (0,1) for x in self.plan['decisions']))


class G7OriginalArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        keys=('G7_ORIGINAL','G7_SOURCE','G7_TRAIN','G7_PAID')
        if not all(os.environ.get(z) for z in keys):
            raise unittest.SkipTest('requires original archive, train and independent physically paid outputs')
        cls.paths={k:Path(os.environ[k]) for k in keys}
        cls.original=cls.paths['G7_ORIGINAL'].read_bytes()
        cls.public=clean_json(cls.paths['G7_SOURCE']);cls.train=clean_json(cls.paths['G7_TRAIN']);cls.paid=clean_json(cls.paths['G7_PAID'])

    def test_01_genuine_independent_human_review(self):
        result=independently_score(self.original,self.public,self.train,self.paid)
        self.assertEqual(result['historical_held_questions'],96)
        self.assertEqual(result['actions']['ndu'],result['actions']['bellman'])
        self.assertFalse(result['ndu_specific_task_gain_verified'])

    def test_02_postseal_authority_forgery_rejected(self):
        fake=copy.deepcopy(self.paid);fake['production_authorized']=True
        fake['digest']=hash_object({k:v for k,v in fake.items() if k!='digest'})
        with self.assertRaises(ValueError):independently_score(self.original,self.public,self.train,fake)

    def test_03_unpaid_rerank_relabel_rejected(self):
        fake=copy.deepcopy(self.paid)
        bm=next(x for x in fake['decisions'] if x['ndu']['action']=='BM25')
        bm['ndu']['top10']=list(reversed(bm['ndu']['top10']))
        fake['digest']=hash_object({k:v for k,v in fake.items() if k!='digest'})
        with self.assertRaises(ValueError):independently_score(self.original,self.public,self.train,fake)

    def test_04_wrong_source_input_denied(self):
        fake=copy.deepcopy(self.public);fake['roots'][0]['questions'][0]['train_support']=['D1:999999']
        with self.assertRaises(ValueError):independently_score(self.original,fake,self.train,self.paid)

    def test_05_paid_original_forward_underbilling_denied(self):
        fake=copy.deepcopy(self.paid)
        key=next(iter(fake['by_root_and_policy_cost']))
        fake['by_root_and_policy_cost'][key]['encoder_sequences']-=1
        fake['digest']=hash_object({k:v for k,v in fake.items() if k!='digest'})
        with self.assertRaises(ValueError):independently_score(self.original,self.public,self.train,fake)

    def test_06_forged_stable_label_aware_plan_denied(self):
        fake=copy.deepcopy(self.train)
        fake['sealed_plan']['decisions'][0]['ndu']='RERANK'
        fake['sealed_plan']['digest']=hash_object({k:v for k,v in fake['sealed_plan'].items() if k!='digest'})
        fake['digest']=hash_object({k:v for k,v in fake.items() if k!='digest'})
        with self.assertRaises(ValueError):independently_score(self.original,self.public,fake,self.paid)

    def test_07_same_original_model_experiment_denied_no_future(self):
        result=independently_score(self.original,self.public,self.train,self.paid)
        self.assertFalse(result['future_task_quality_verified'])
        self.assertEqual(result['disposition'],'HOLD_NO_GO')


if __name__=='__main__':unittest.main()
