"""V17 source-only mechanism/adversarial checks, NOT real model efficacy."""
import copy
from hashlib import sha256
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import v17_source_focusing as v


class Toy:
    def __init__(self):
        self.src={'families':{}}; self.routes={}; self.parent={'cases':[],
            'schema':v.PARENT_SCHEMA+'.answer-dependent-precommitted-plan',
            'reader_sha256':v.READER_SHA,'tokenizer_sha256':v.TOKEN_SHA}
        for f in ('conv-47','conv-48','conv-49','conv-50'):
            docs=[];qs=[]
            for i in range(8):
                wid=f+'-w'+str(i);bid=f+'-b'+str(i);cid=f+'-c'+str(i)
                docs += [dict(id=wid,text=f'Person {i} of {f} bought lunch. Later person {i} of {f} visited Paris! The meeting went well.'),
                         dict(id=bid,text='Another source with different information.'),dict(id=cid,text='Some unrelated notes.')]
                qid=f+'/q'+str(i)
                qs.append(dict(id=qid,text=f'Where did person {i} of {f} go?'))
                self.routes[qid]=dict(top32=[bid,cid,wid])
                self.parent['cases'].append(dict(id=qid,family=f,cohort='literal_in_annotated_source' if i<4 else 'not_literal_in_annotated_source',witness_id=wid,
                     arms={'witness':dict(evidence_ids=[wid,bid,cid]),'lesion':dict(evidence_ids=[bid,cid])}))
            self.src['families'][f]=dict(passages=docs,questions=qs)
        self.ranks={'schema':'synthetic-source-only'}
    def build(self):
        with patch.object(v,'validate_v16'),patch.object(v,'source_and_rank',return_value=self.routes):
            return v.build(self.src,self.ranks,self.parent)
    def verify(self,p):
        with patch.object(v,'validate_v16'),patch.object(v,'source_and_rank',return_value=self.routes):
            return v.verify_plan(p,self.src,self.ranks,self.parent)


class V17SourceMechanism(unittest.TestCase):
    def test_focus_is_original_contiguous_sentence(self):
        text='Alice bought bread. After lunch Alice went to Berlin! She returned by train.'
        s,off,n=v.selected_sentences('Where did Alice go after lunch?',text)
        self.assertEqual(s,'After lunch Alice went to Berlin!')
        self.assertEqual(text[off[0]:off[1]],s)
        self.assertEqual(n,3)
    def test_no_new_source_tokens_in_focus(self):
        x='Ada worked in Paris. She often played music.'
        s,span,_=v.selected_sentences('Where did Ada work?',x)
        self.assertEqual(x[span[0]:span[1]],s)
    def test_single_sentence_kept(self):
        s,span,n=v.selected_sentences('Where?', 'Bob: Mountain resort')
        self.assertEqual((s,n),('Bob: Mountain resort',1))
        self.assertEqual(span,[0,len(s)])
    def test_missing_question_denied(self):
        with self.assertRaises(ValueError):v.selected_sentences('', 'source')
    def test_missing_source_denied(self):
        with self.assertRaises(ValueError):v.selected_sentences('question', '')
    def test_oversized_source_denied(self):
        with self.assertRaises(ValueError):v.selected_sentences('question', 'x'*3001)
    def test_prompt_contains_original_three_ids(self):
        p=v.original_prompt('Where?',['a','b','c'],{'a':'AAA','b':'BBB','c':'CCC'},focused=True)
        self.assertIn('[E1] AAA',p);self.assertIn('[E2] BBB',p);self.assertIn('[E3] CCC',p)
    def test_duplicate_evidence_denied(self):
        with self.assertRaises(ValueError):v.original_prompt('What?',['x','x','y'],{'x':'v','y':'w'},focused=True)
    def test_missing_evidence_denied(self):
        with self.assertRaises(ValueError):v.original_prompt('What?',['x','y','missing'],{'x':'v','y':'w'},focused=False)
    def test_build_complete_32_64(self):
        p=Toy().build()
        self.assertEqual((len(p['cases']),len(p['requests'])),(32,64))
        self.assertEqual(p['source_changed_cases'],32)
        self.assertFalse(p['new_focus_uses_publisher_answers'])
        self.assertFalse(p['production_authorized'])
    def test_exact_plan_verifies(self):
        toy=Toy();p=toy.build();self.assertEqual(toy.verify(p),p)
    def test_changed_model_identity_denied(self):
        toy=Toy();p=toy.build();p['reader_weights_sha256']='0'*64
        with self.assertRaises(ValueError):toy.verify(p)
    def test_added_gold_field_denied(self):
        toy=Toy();p=toy.build();p['publisher_gold']='leak'
        with self.assertRaises(ValueError):toy.verify(p)
    def test_source_revision_denied(self):
        toy=Toy();p=toy.build();toy.src['families']['conv-47']['passages'][0]['text']='changed'
        with self.assertRaises(ValueError):toy.verify(p)
    def test_evidence_id_alias_denied(self):
        toy=Toy();p=toy.build();p['cases'][0]['witness_id']='forged'
        with self.assertRaises(ValueError):toy.verify(p)
    def test_focusing_not_publisher_answer_conditioned(self):
        toy=Toy();p=toy.build();p['new_focus_uses_publisher_answers']=True
        with self.assertRaises(ValueError):toy.verify(p)
    def test_same_source_repeated_arms_distinct_request(self):
        toy=Toy();p=toy.build()
        for item in p['cases']:
            self.assertNotEqual(item['arms']['formatted_focused'],item['arms']['formatted_full'])
    def test_raw_recount_missing_answer_denied(self):
        toy=Toy();plan=toy.build();physical={'schema':v.SCHEMA+'.original-physical-answers','plan_sha256':v.digest(plan),
              'raw_answers':{},'requests':0}
        with self.assertRaises(ValueError):v.raw_recount(plan,physical,[],None)
    def test_original_model_false_claim_denied(self):
        toy=Toy();plan=toy.build();physical={'schema':v.SCHEMA+'.original-physical-answers','plan_sha256':v.digest(plan),
              'raw_answers':{},'requests':64,'model_sha256':'fake'}
        with self.assertRaises(ValueError):v.raw_recount(plan,physical,[],None)
    def test_create_only(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'test.json';v.sealed(path,{'a':1})
            with self.assertRaises(FileExistsError):v.sealed(path,{'a':2})
    def test_no_postseal_question_count_substitution(self):
        toy=Toy();plan=toy.build()
        with self.assertRaises(ValueError):v.score_after_seal(plan,{'plan_sha256':v.digest(plan),'requests':63},
                                                   toy.parent,{'plan_sha256':v.digest(toy.parent),'requests':128},[])
    def test_no_missing_qa_original(self):
        toy=Toy();plan=toy.build()
        with self.assertRaises(ValueError):v.score_after_seal(plan,{'plan_sha256':'modified','requests':64},
                                                   toy.parent,{'plan_sha256':v.digest(toy.parent),'requests':128},[])

if __name__=='__main__':unittest.main()
