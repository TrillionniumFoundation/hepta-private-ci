"""Synthetic contract and adversarial tests. No real model/heldout qualification."""
import copy
import json
import math
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import stem_v13_cheap_retrieval as v
from v13_independent_reviewer import bm25_independent
from v13_retrieval_cost import BM25Only

class Protocol(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw=[]
        for fi,(fam,nq) in enumerate(v.QUESTION_COUNTS.items()):
            # Complete 5,882-source roster, but entirely synthetic grammar.
            n=589 if fi<2 else 588
            turns=[dict(dia_id='s'+str(i),speaker='A',text='alice lives in denver item '+str(i)) for i in range(n)]
            qs=[dict(question='where does Alice live?',answer='DENVER',evidence=['s0']) for _ in range(nq)]
            raw.append(dict(sample_id=fam,conversation={'session_1':turns},qa=qs))
        cls.source=v.source_only(raw)
        cls.plan=v.plan_for(cls.source)
        routes=[]
        for fam,a in cls.source['families'].items():
            fixed=[x['id'] for x in a['passages'][:32]]
            for q in a['questions']:
                routes.append({'id':q['id'],'family':fam,'top32':{arm:list(fixed) for arm in v.ARMS}})
        cls.routes=dict(schema=v.SCHEMA+'.ranked',plan_sha256=v.digest(cls.plan),source_sha256=v.digest(cls.source),
                        config_sha256=v.digest(v.CONFIG),case_count=1986,source_turn_count=5882,cases=routes,
                        model_forward_count=0,trained_head_parameters=0,publisher_gold_loaded=False,production_authorized=False)
    def clone(self):return copy.deepcopy(self.routes)
    def test_complete_synthetic_census(self):
        v.assert_source(self.source);v.validate_routes(self.source,self.plan,self.routes)
        self.assertEqual(len(self.routes['cases']),1986)
    def test_json_plan_roundtrip_is_identical(self):
        self.assertEqual(json.loads(v.jbytes(self.plan)),self.plan)
    def test_plan_identity_rejects_swap(self):
        x=copy.deepcopy(self.plan);x['precommitted_primary']='char_only'
        with self.assertRaises(ValueError):v.validate_routes(self.source,x,self.routes)
    def test_publisher_gold_field_rejected(self):
        x=copy.deepcopy(self.source);x['families']['conv-47']['questions'][0]['evidence']=['s0']
        with self.assertRaises(ValueError):v.assert_source(x)
    def test_source_answer_field_rejected(self):
        x=copy.deepcopy(self.source);x['families']['conv-47']['questions'][0]['answer']='DENVER'
        with self.assertRaises(ValueError):v.assert_source(x)
    def test_source_extra_fields_rejected(self):
        x=copy.deepcopy(self.source);x['gold']={'conv-47/q1':['s0']}
        with self.assertRaises(ValueError):v.assert_source(x)
    def test_duplicate_source_rejected(self):
        x=copy.deepcopy(self.source);x['families']['conv-48']['passages'][1]['id']='s0'
        with self.assertRaises(ValueError):v.assert_source(x)
    def test_missing_source_family_rejected(self):
        x=copy.deepcopy(self.source);del x['families']['conv-50']
        with self.assertRaises(ValueError):v.assert_source(x)
    def test_mutated_request_rejected(self):
        x=self.clone();x['cases'][0]['id']='conv-47/q0'
        with self.assertRaises(ValueError):v.validate_routes(self.source,self.plan,x)
    def test_missing_request_rejected(self):
        x=self.clone();x['cases'].pop()
        with self.assertRaises(ValueError):v.validate_routes(self.source,self.plan,x)
    def test_duplicate_evidence_rejected(self):
        x=self.clone();x['cases'][0]['top32']['bm25'][1]='s0'
        with self.assertRaises(ValueError):v.validate_routes(self.source,self.plan,x)
    def test_outside_source_evidence_rejected(self):
        x=self.clone();x['cases'][0]['top32']['bm25'][0]='UNDELIVERED'
        with self.assertRaises(ValueError):v.validate_routes(self.source,self.plan,x)
    def test_missing_arm_rejected(self):
        x=self.clone();del x['cases'][0]['top32']['char']
        with self.assertRaises(ValueError):v.validate_routes(self.source,self.plan,x)
    def test_duplicate_case_rejected(self):
        x=self.clone();x['cases'][1]['id']=x['cases'][0]['id']
        with self.assertRaises(ValueError):v.validate_routes(self.source,self.plan,x)
    def test_forged_model_forward_rejected(self):
        x=self.clone();x['model_forward_count']=1
        with self.assertRaises(ValueError):v.validate_routes(self.source,self.plan,x)
    def test_claimed_promotion_rejected(self):
        x=self.clone();x['production_authorized']=True
        with self.assertRaises(ValueError):v.validate_routes(self.source,self.plan,x)
    def test_fake_gold_before_rank_rejected(self):
        x=self.clone();x['publisher_gold_loaded']=True
        with self.assertRaises(ValueError):v.validate_routes(self.source,self.plan,x)
    def test_changed_source_sha_rejected(self):
        x=self.clone();x['source_sha256']='0'*64
        with self.assertRaises(ValueError):v.validate_routes(self.source,self.plan,x)
    def test_rank_source_rejects_changed_plan_before_compute(self):
        x=copy.deepcopy(self.plan);x['frozen_config']['primary']='char_only'
        with self.assertRaises(ValueError):v.rank_source(self.source,x)
    def test_numeric_rank_is_finite(self):
        docs=[{'id':'z','text':'Alice lives in Paris'},{'id':'b','text':'Bob works in Denver'},{'id':'a','text':'Alice is a doctor in Paris'}]
        ind=v.Index(docs)
        ranks=ind.rank('Where does Alice live in Paris?')
        self.assertEqual(set(ranks),set(v.ARMS))
        self.assertEqual(ranks['bm25'][:3],bm25_independent('Where does Alice live in Paris?',docs))
    def test_reference_bm25_index_matches_full_index(self):
        docs=[{'id':str(i),'text':'Alice lives in Paris' if i%3 else 'Bob works in Denver'} for i in range(40)]
        question='Where is Alice living in Paris?'
        self.assertEqual(BM25Only(docs).rank(question),v.Index(docs).rank(question)['bm25'])
    def test_character_normalization(self):
        self.assertEqual(v.grams(v.words('ＣＡＦＥ')) ,v.grams(v.words('cafe')))
    def test_no_phrase_query_is_bounded(self):
        docs=[{'id':str(i),'text':'milk wool '*(i+1)} for i in range(5)]
        ranked=v.Index(docs).rank('Milk')
        self.assertEqual(len(ranked['phrase_char']),5)
    def test_unknown_query_deterministic_tie(self):
        docs=[{'id':'z','text':'one'},{'id':'a','text':'two'},{'id':'b','text':'three'}]
        ranked=v.Index(docs).rank('PseudofeatureUnseen')
        self.assertEqual(ranked['bm25'],['a','b','z'])
    def test_blank_question_refused(self):
        docs=[{'id':str(i),'text':'word'} for i in range(5)]
        with self.assertRaises(ValueError):v.Index(docs).rank(' ! ')
    def test_nonfinite_json_rejected(self):
        with TemporaryDirectory() as d:
            p=Path(d)/'a.json';p.write_text('{"a":NaN}')
            with self.assertRaises(ValueError):v.read_json(p)
    def test_duplicate_json_key_rejected(self):
        with TemporaryDirectory() as d:
            p=Path(d)/'a.json';p.write_text('{"a":1,"a":2}')
            with self.assertRaises(ValueError):v.read_json(p)
    def test_create_once_file(self):
        with TemporaryDirectory() as d:
            p=Path(d)/'result.json';v.write_once(p,{'ok':True})
            with self.assertRaises(FileExistsError):v.write_once(p,{'ok':False})
    def test_synthetic_score_denied_as_original_historical(self):
        raw=[{'sample_id':fam,'qa':[{'evidence':['s0']} for _ in range(nq)]} for fam,nq in v.QUESTION_COUNTS.items()]
        with self.assertRaises(ValueError):v.score_result(self.source,self.plan,self.routes,raw)

if __name__=='__main__':unittest.main()
