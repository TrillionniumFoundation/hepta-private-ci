"""G8 source/adversarial + optional genuine original numeric regression tests."""
from __future__ import annotations
import copy
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import sys
import unittest

from g8_source import SCHEMA as SOURCE_SCHEMA,DOM as SOURCE_DOM,validate,pack
from g8_policy import (freeze,validate_profile,ndu_backward,bellman_forward,
                        available,plan,verify_plan,expected_utility,BANDS,ACTIONS,digest)
from g6_coverage_source import TRAIN,HELD,sha,canonical
from real_minilm_reference import CHECKSUMS


def fake_source():
    roots=[]
    for name in sorted(TRAIN+HELD):
        docs=[]
        for i in range(300):
            text=f'Conversation {name} source speaker A mentions location {i}'
            docs.append({'id':f'D1:{i}','text':text,'text_sha':sha(text.encode())})
        docs.sort(key=lambda item:item['id'])
        q=[]
        for i in range(24):
            text=f'Which answer is supported by statement {i} in {name}?'
            x={'id':f'q{i}','text':text,'text_sha':sha(text.encode())}
            if name in TRAIN:x['train_support']=['D1:1']
            q.append(x)
        roots.append({'root':name,'split':'TRAIN' if name in TRAIN else 'HELD',
                      'docs':docs,'questions':q})
    p={'schema':SOURCE_SCHEMA,'original_sha':CHECKSUMS['locomo.json'],
       'model_sha':CHECKSUMS['encoder/model.safetensors'],
       'predecessor_g6_digest':'a'*64,
       'corpus_mode':'complete_original_utterances_in_both_train_and_held',
       'question_roster':'frozen_G5_24_per_original_source',
       'shortlist_size':64,'roots':roots,
       'historically_public_not_prospective':True,'held_gold_exported':False,
       'research_only':True,'production_authorized':False,'disposition':'HOLD_NO_GO'}
    p['digest']=pack(p)
    validate(p)
    return p


def fake_train(p):
    output=[]
    for r in p['roots']:
        if r['root'] not in TRAIN:continue
        for i,q in enumerate(r['questions']):
            kind=BANDS[i%3]
            bm=kind!='strong'; rr=True
            ids_b=[f'D1:{k}' for k in (range(1,11) if bm else range(50,60))]
            ids_r=[f'D1:{k}' for k in range(1,11)]
            output.append({'root':r['root'],'qid':q['id'],'source_sha':q['text_sha'],
                     'band':kind,'bm25_hit':bm,'rrf_hit':rr,
                     'bm25_top10':ids_b,'rrf_top10':ids_r})
    return output


def fake_held(p):
    from g6_coverage_model import bm25_all
    from g7_policy import feature_band
    out=[]
    for r in p['roots']:
        if r['root'] not in HELD:continue
        ranks,_=bm25_all(r['docs'],r['questions'])
        for i,q in enumerate(r['questions']):
            out.append({'root':r['root'],'qid':q['id'],'source_sha':q['text_sha'],
                        'band':feature_band(q['text'],r['docs'][ranks[i][0]]['text']),
                        'bm25_top10':[r['docs'][j]['id'] for j in ranks[i][:10]]})
    return sorted(out,key=lambda r:(r['root'],r['qid']))


class G8SourceOnlyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.public=fake_source()
        cls.train=fake_train(cls.public)
        cls.profile=freeze(cls.public,cls.train)
        cls.held=fake_held(cls.public)
        cls.planned=plan(cls.public,cls.profile,cls.held)

    def test_source_exact_roots(self):
        self.assertEqual(len(self.public['roots']),10)
        self.assertEqual(sum(len(r['docs']) for r in self.public['roots']),3000)

    def test_source_has_train_evidence_but_never_held_evidence(self):
        self.assertTrue(all('train_support' in q for r in self.public['roots'] if r['split']=='TRAIN' for q in r['questions']))
        self.assertTrue(all('train_support' not in q for r in self.public['roots'] if r['split']=='HELD' for q in r['questions']))

    def test_source_checksum_rejects_mutation(self):
        p=copy.deepcopy(self.public);p['roots'][0]['docs'][0]['text']='changed'
        with self.assertRaises(ValueError):validate(p)

    def test_source_resealed_unknown_held_gold_rejected(self):
        p=copy.deepcopy(self.public)
        next(r for r in p['roots'] if r['root'] in HELD)['questions'][0]['gold']=['D1:1']
        p['digest']=pack({k:v for k,v in p.items() if k!='digest'})
        with self.assertRaises(ValueError):validate(p)

    def test_source_resealed_hidden_extra_root_rejected(self):
        p=copy.deepcopy(self.public);p['roots'].pop()
        p['digest']=pack({k:v for k,v in p.items() if k!='digest'})
        with self.assertRaises(ValueError):validate(p)

    def test_source_resealed_duplicate_document_denied(self):
        p=copy.deepcopy(self.public);p['roots'][0]['docs'][1]=p['roots'][0]['docs'][0]
        p['digest']=pack({k:v for k,v in p.items() if k!='digest'})
        with self.assertRaises(ValueError):validate(p)

    def test_train_only_complete_144(self):
        self.assertEqual(sum(x['observations'] for x in self.profile['bands'].values()),144)

    def test_full_train_source_no_held_label_in_freeze(self):
        rows=copy.deepcopy(self.train);rows[0]['held_support']=['D1:1']
        with self.assertRaises(ValueError):freeze(self.public,rows)

    def test_inconsistent_train_bool_rejected(self):
        rows=copy.deepcopy(self.train);rows[0]['rrf_hit']=not rows[0]['rrf_hit']
        with self.assertRaises(ValueError):freeze(self.public,rows)

    def test_duplicate_train_question_rejected(self):
        rows=copy.deepcopy(self.train);rows[0]=rows[1]
        with self.assertRaises(ValueError):freeze(self.public,rows)

    def test_train_wrong_source_sha_rejected(self):
        rows=copy.deepcopy(self.train);rows[0]['source_sha']='0'*64
        with self.assertRaises(ValueError):freeze(self.public,rows)

    def test_train_injected_outside_document_rejected(self):
        rows=copy.deepcopy(self.train);rows[0]['rrf_top10'][0]='D9:999'
        with self.assertRaises(ValueError):freeze(self.public,rows)

    def test_train_duplicate_rerank_reference_rejected(self):
        rows=copy.deepcopy(self.train);rows[0]['rrf_top10'][1]=rows[0]['rrf_top10'][0]
        with self.assertRaises(ValueError):freeze(self.public,rows)

    def test_training_no_original_gold_for_held(self):
        self.assertFalse(self.planned['original_held_gold_accessed'])
        self.assertEqual(len(self.planned['choices']),96)

    def test_policy_requires_source_disjoint_positive_gain(self):
        self.assertTrue(self.profile['bands']['strong']['rerank_admitted'])
        self.assertFalse(self.profile['bands']['medium']['rerank_admitted'])
        self.assertFalse(self.profile['bands']['weak']['rerank_admitted'])

    def test_no_unsupported_stop_from_only_six_roots(self):
        self.assertTrue(all(v['stop_admitted'] is False for v in self.profile['bands'].values()))
        for b in BANDS:
            with self.assertRaises(ValueError):expected_utility(self.profile,b,'STOP')

    def test_stop_cannot_be_injected_by_resealed_profile(self):
        p=copy.deepcopy(self.profile);p['bands']['weak']['stop_admitted']=True
        p['digest']=digest({k:v for k,v in p.items() if k!='digest'})
        with self.assertRaises(ValueError):validate_profile(p,self.public)

    def test_unqualified_rerank_rejected(self):
        with self.assertRaises(ValueError):expected_utility(self.profile,'weak','RERANK')

    def test_valid_guarded_rerank_gain_positive(self):
        self.assertGreater(expected_utility(self.profile,'strong','RERANK'),
                           expected_utility(self.profile,'strong','BM25'))

    def test_bellman_same_profile_full_horizon(self):
        for n in range(1,25):
            xs=[BANDS[(i*7+n)%3] for i in range(n)]
            for cap in range(9):
                self.assertEqual(ndu_backward(self.profile,xs,cap),
                                 bellman_forward(self.profile,xs,cap))

    def test_budget_exactly_bounded(self):
        xs=['strong']*24
        for cap in range(9):
            result=ndu_backward(self.profile,xs,cap)
            self.assertEqual(sum(x=='RERANK' for x in result),cap)

    def test_bad_horizon_denied(self):
        with self.assertRaises(ValueError):ndu_backward(self.profile,['strong']*25,8)

    def test_float_lookalike_budget_denied(self):
        with self.assertRaises(ValueError):bellman_forward(self.profile,['strong'],8.0)

    def test_plan_exact_no_hidden_future(self):
        self.assertFalse(self.planned['prospective_validation'])
        self.assertEqual({r['root'] for r in self.planned['choices']},set(HELD))
        verify_plan(self.public,self.profile,self.planned)

    def test_plan_action_tamper_rejected_even_after_reseal(self):
        p=copy.deepcopy(self.planned);p['choices'][0]['ndu']='STOP'
        p['digest']=digest({k:v for k,v in p.items() if k!='digest'})
        with self.assertRaises(ValueError):verify_plan(self.public,self.profile,p)

    def test_plan_source_tamper_rejected_even_after_reseal(self):
        p=copy.deepcopy(self.planned);p['choices'][0]['bm25_top10'][0]='D2:19'
        p['digest']=digest({k:v for k,v in p.items() if k!='digest'})
        with self.assertRaises(ValueError):verify_plan(self.public,self.profile,p)

    def test_plan_conflicting_held_question_rejected(self):
        rows=copy.deepcopy(self.held);rows[0]=rows[1]
        with self.assertRaises(ValueError):plan(self.public,self.profile,rows)

    def test_extra_band_rejected(self):
        with self.assertRaises(ValueError):available(self.profile,'other')

    def test_pure_source_import_does_not_load_model(self):
        self.assertNotIn('torch',sys.modules)
        self.assertNotIn('safetensors',sys.modules)


class G8HistoricalOriginalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root=os.environ.get('G8_EVIDENCE_DIR')
        original=os.environ.get('G8_ORIGINAL')
        if not root or not original:
            raise unittest.SkipTest('requires original SHA-pinned LoCoMo, prelabel sealed CPU receipts')
        cls.root=Path(root);cls.raw=Path(original).read_bytes()
        cls.public=json.loads((cls.root/'public.json').read_bytes())
        cls.roots=[json.loads((cls.root/f'train-{n}.json').read_bytes()) for n in TRAIN]
        cls.assembled=json.loads((cls.root/'assembled_private.json').read_bytes())
        cls.paid=json.loads((cls.root/'paid_prelabel_private.json').read_bytes())

    def test_original_source_regenerated(self):
        from g8_source import build
        self.assertEqual(build(self.raw),self.public)

    def test_historical_original_independent_exact_result(self):
        from g8_review import review
        result=review(self.raw,self.public,self.roots,self.assembled,self.paid)
        self.assertEqual(result['arms']['ndu'],result['arms']['bellman'])
        self.assertEqual(result['arms']['ndu'],result['arms']['bm25'])
        self.assertEqual(result['arms']['ndu']['hit_at_5'],48)
        self.assertEqual(result['train_original_model_sequences'],2759)
        self.assertEqual(result['paid_original_model_sequences'],1147)

    def test_original_publisher_mutation_denied(self):
        from g8_review import review
        bad=self.raw[:-1]+b' '
        with self.assertRaises(ValueError):
            review(bad,self.public,self.roots,self.assembled,self.paid)

    def test_tampered_historical_prediction_rejected(self):
        from g8_review import review
        p=copy.deepcopy(self.paid);p['decisions'][0]['bm25_top10'].reverse()
        p['digest']=digest({k:v for k,v in p.items() if k!='digest'})
        with self.assertRaises(ValueError):
            review(self.raw,self.public,self.roots,self.assembled,p)

    def test_tampered_training_outcomes_rejected(self):
        from g8_review import review
        a=copy.deepcopy(self.assembled)
        a['train_observations'][0]['rrf_hit']=not a['train_observations'][0]['rrf_hit']
        a['digest']=digest({k:v for k,v in a.items() if k!='digest'})
        with self.assertRaises(ValueError):
            review(self.raw,self.public,self.roots,a,self.paid)

    def test_original_malformed_model_census_rejected(self):
        from g8_review import review
        p=copy.deepcopy(self.paid);p['actual_pretrained_sequence_forwards']-=1
        p['digest']=digest({k:v for k,v in p.items() if k!='digest'})
        with self.assertRaises(ValueError):
            review(self.raw,self.public,self.roots,self.assembled,p)


if __name__=='__main__':unittest.main()
