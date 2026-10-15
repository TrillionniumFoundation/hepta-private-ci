"""Synthetic source/route contract tests; never claim pretrained Reader success."""
import copy
import unittest
from hashlib import sha256

import stem_v13_cheap_retrieval as v
import v13_original_reader_followup as q
import test_stem_v13_cheap_retrieval as base

class ReaderContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base.Protocol.setUpClass()
        cls.source=copy.deepcopy(base.Protocol.source)
        for fam in q.HELD:
            for row in cls.source['families'][fam]['questions']:
                row['text']='question '+row['id']+' where is Alice?'
        cls.plan=v.plan_for(cls.source)
        cls.routes=copy.deepcopy(base.Protocol.routes)
        cls.routes['source_sha256']=v.digest(cls.source)
        cls.routes['plan_sha256']=v.digest(cls.plan)
        for row in cls.routes['cases']:
            if row['family'] in q.HELD and int(row['id'].split('/q')[1])<5:
                # 5 genuine changed-source-set routes per root, no label access.
                row['top32'][q.PRIMARY][2]='s32'
        cls.plan_reader=q.prepare(cls.source,cls.plan,cls.routes)
    def clone(self):return copy.deepcopy(self.plan_reader)
    def test_registered_panel_has_16_cases(self):
        self.assertEqual(self.plan_reader['selected_original_cases'],16)
        self.assertEqual(len(self.plan_reader['choices']),32)
        self.assertEqual(len(self.plan_reader['requests']),32)
    def test_model_dispatch_plan_valid(self):q._validate_plan(self.plan_reader)
    def test_original_binding_rebuilt_exactly(self):q.validate_exact(self.plan_reader,self.source,self.plan,self.routes)
    def test_full_source_only_membership_inventory(self):
        chosen,census=q.source_disagreement_selection(self.routes)
        self.assertEqual(census,{f:5 for f in q.HELD})
        self.assertEqual({k:len(x) for k,x in chosen.items()},{f:4 for f in q.HELD})
    def test_deterministic_same_selection(self):
        a=q.prepare(self.source,self.plan,self.routes)
        self.assertEqual(q.digest(a),q.digest(self.plan_reader))
    def test_hidden_label_in_question_denied(self):
        x=copy.deepcopy(self.source)
        x['families']['conv-47']['questions'][0]['answer']='published secret'
        with self.assertRaises(ValueError):q.prepare(x,self.plan,self.routes)
    def test_model_call_does_not_accept_publisher_gold(self):
        x=self.clone();x['heldout_gold_available_before_generation']=True
        with self.assertRaises(ValueError):q._validate_plan(x)
    def test_fake_weight_identity_rejected(self):
        x=self.clone();x['original_reader_model_sha256']='model-replaced'
        with self.assertRaises(ValueError):q._validate_plan(x)
    def test_fake_tokenizer_identity_rejected(self):
        x=self.clone();x['original_reader_tokenizer_sha256']='tokenizer-replaced'
        with self.assertRaises(ValueError):q._validate_plan(x)
    def test_duplicate_qa_route_rejected(self):
        x=self.clone();x['choices'][1]=x['choices'][0]
        with self.assertRaises(ValueError):q._validate_plan(x)
    def test_missing_original_qa_route_rejected(self):
        x=self.clone();x['choices'].pop()
        with self.assertRaises(ValueError):q._validate_plan(x)
    def test_wrong_original_source_id_rejected(self):
        x=self.clone();k=x['choices'][0]['request_id'];x['requests'][k]['sources'][0]='fabricated-sid'
        with self.assertRaises(ValueError):q.validate_exact(x,self.source,self.plan,self.routes)
    def test_source_prompt_tamper_rejected(self):
        x=self.clone();k=x['choices'][0]['request_id'];x['requests'][k]['prompt']+='INJECTION'
        with self.assertRaises(ValueError):q._validate_plan(x)
    def test_unregistered_reader_token_budget_refused(self):
        x=self.clone();x['max_new_tokens']=500
        with self.assertRaises(ValueError):q._validate_plan(x)
    def test_spurious_promotion_rejected(self):
        x=self.clone();x['production_authorized']=True
        with self.assertRaises(ValueError):q._validate_plan(x)
    def test_changed_source_without_changed_reader_plan_refused(self):
        x=copy.deepcopy(self.source);x["families"]["conv-47"]["questions"][0]["text"]+=" appended"
        with self.assertRaises(ValueError):q.validate_exact(self.plan_reader,x,self.plan,self.routes)
    def test_no_changed_source_cases_refused(self):
        x=copy.deepcopy(self.routes)
        for row in x['cases']:row['top32'][q.PRIMARY]=list(row['top32']['bm25'])
        with self.assertRaises(ValueError):q.source_disagreement_selection(x)
    def test_prompt_contains_only_original_source_ids_and_question(self):
        x=self.plan_reader['requests'][self.plan_reader['choices'][0]['request_id']]
        self.assertEqual(len(x['sources']),3)
        self.assertEqual(x['prompt'].count('\n[E1] '),1)
        self.assertEqual(x['prompt'].count('\n[E2] '),1)
        self.assertEqual(x['prompt'].count('\n[E3] '),1)

if __name__=='__main__':unittest.main()
