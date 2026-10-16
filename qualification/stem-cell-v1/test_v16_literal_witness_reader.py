"""V16 synthetic contracts only. Does not assert original pretrained efficacy."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import v16_literal_witness_reader as v


def fixture():
    src={'families':{}}
    orig=[];rank={}
    families=['conv-26','conv-30','conv-41','conv-42','conv-43','conv-44',*v.HELD]
    for fam in families:
        docs=[{'id':f'd{i}', 'text':f'Speaker: opaque line {i}'} for i in range(3)]
        docs.append({'id':'literal','text':'Speaker: Alice moved to Stockholm in September'})
        docs.append({'id':'nonliteral','text':'Speaker: an unhelpful nonliteral conversation'})
        qs=[];qa=[]
        n=8 if fam in v.HELD else 0
        for k in range(n):
            ident=f'{fam}/q{k}';qs.append({'id':ident,'text':f'What happened event {fam} {k}?'})
            qa.append({'answer':'Stockholm' if k<4 else 'Helsinki',
                       'evidence':['literal' if k<4 else 'nonliteral']})
            rank[ident]={'id':ident,'family':fam,'top32':['d0','d1','d2','literal','nonliteral']}
        src['families'][fam]={'passages':docs,'questions':qs}
        orig.append({'sample_id':fam,'qa':qa})
    return src,rank,orig


def mock_reader():
    return patch.object(v,'source_and_rank',side_effect=lambda src,ranks:ranks)


class Contract(unittest.TestCase):
    def setUp(self):
        self.src,self.rank,self.original=fixture()
        with mock_reader():self.plan=v.construct(self.src,self.rank,self.original)
    def valid(self,plan=None):
        with mock_reader():return v.validate(plan or self.plan,self.src,self.rank)
    def reject(self,change):
        plan=copy.deepcopy(self.plan);change(plan)
        with self.assertRaises(ValueError):self.valid(plan)
    def test_canonical_plan(self):
        self.assertTrue(self.valid());self.assertEqual(len(self.plan['cases']),32)
        self.assertEqual(len(self.plan['requests']),128)
        self.assertTrue(self.plan['answer_dependent_historical_selection'])
    def test_literal_boundary(self):
        self.assertTrue(v.literal_answer({'answer':'Stockholm'},'I live in Stockholm.'))
        self.assertFalse(v.literal_answer({'answer':'yes'},'yes'))
        self.assertFalse(v.literal_answer({'answer':'Helsinki'},'I live in Stockholm.'))
        self.assertFalse(v.literal_answer({'answer':12},'12'))
    def test_expected_source_cohorts(self):
        by={(x['family'],x['cohort']) for x in self.plan['cases']}
        self.assertEqual(len(by),8)
    def test_no_held_answers_in_prompt(self):
        requests=list(self.plan['requests'].values())
        self.assertFalse(any('Publisher answer:' in x['prompt'] for x in requests))
    def test_plan_fake_reference(self):self.reject(lambda x:x.__setitem__('stronger_reference_reader_executed',True))
    def test_plan_fake_human(self):self.reject(lambda x:x.__setitem__('independent_semantic_adjudication',True))
    def test_plan_fake_future(self):self.reject(lambda x:x.__setitem__('calendar_future_windows',1))
    def test_plan_fake_production(self):self.reject(lambda x:x.__setitem__('production_authorized',True))
    def test_plan_claim_gold_blind(self):self.reject(lambda x:x.__setitem__('answer_dependent_historical_selection',False))
    def test_plan_fake_containment_proof(self):self.reject(lambda x:x.__setitem__('literal_containment_not_human_sufficiency',False))
    def test_wrong_weights(self):self.reject(lambda x:x.__setitem__('reader_sha256','0'*64))
    def test_request_omission(self):self.reject(lambda x:x['requests'].pop(next(iter(x['requests']))))
    def test_request_content_tamper(self):
        self.reject(lambda x:x['requests'][next(iter(x['requests']))].__setitem__('prompt','changed'))
    def test_source_id_swapped(self):
        self.reject(lambda x:x['cases'][0]['arms']['witness'].__setitem__('evidence_ids',['d0','d1','d2']))
    def test_request_same_id_twice(self):
        self.reject(lambda x:x['cases'][0]['arms']['witness'].__setitem__(
            'request_id',x['cases'][0]['arms']['retrieved']['request_id']))
    def test_wrong_lesion(self):
        self.reject(lambda x:x['cases'][0]['arms']['lesion'].__setitem__('evidence_ids',['literal','d0']))
    def test_case_cohort_changed(self):self.reject(lambda x:x['cases'][0].__setitem__('cohort','novel'))
    def test_duplicate_case(self):self.reject(lambda x:x['cases'].__setitem__(31,copy.deepcopy(x['cases'][0])))
    def test_plan_unexpected_answer(self):self.reject(lambda x:x.__setitem__('publisher_answer','secret'))
    def test_source_independent_eligibility_recount(self):
        wrong=copy.deepcopy(self.original)
        for x in wrong:
            if x['sample_id']=='conv-47':x['qa'][0]['answer']='Tokyo'
        with mock_reader():
            try:
                replan=v.construct(self.src,self.rank,wrong)
            except ValueError:
                return  # Missing eligible group is a valid fail-closed refusal.
        self.assertNotEqual(replan,self.plan)
    def test_seal_create_only(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'receipt.json'
            v.sealed(p,{'a':1})
            with self.assertRaises(FileExistsError):v.sealed(p,{'a':2})
    def test_reject_duplicate_json_key(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'a.json';p.write_text('{"a":1,"a":2}')
            with self.assertRaises(ValueError):v.read(p)
    def test_reject_nan(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'a.json';p.write_text('{"a":NaN}')
            with self.assertRaises(ValueError):v.read(p)
    def test_physical_forward_counter_eos(self):
        from v16_original_reader_recount import forward_count
        self.assertEqual(forward_count([2]),1)
        self.assertEqual(forward_count([42,2]),2)
        self.assertEqual(forward_count([42,41]),3)
    def test_forward_counter_invalid_types(self):
        from v16_original_reader_recount import forward_count
        for seq in ([], [True], [-1], [49152], [2]*25):
            with self.assertRaises(ValueError):forward_count(seq)
    def test_reader_response_missing_provenance(self):
        from v16_original_reader_recount import recount
        with self.assertRaises(ValueError):recount(self.plan,{'raw_answers':{}},[],None)
    def test_strict_reader_answer_census(self):
        with mock_reader():
            packet={'schema':v.SCHEMA+'.actual-original-reader-results',
                    'plan_sha256':v.digest(self.plan),'model_sha256':v.READER_SHA,
                    'tokenizer_sha256':v.TOKEN_SHA,'reader_config_sha256':v.READER_CFG_SHA,
                    'model_forwards':128,'requests':128,'raw_answers':{},
                    'execution_cpu_seconds':1.0,'execution_wall_seconds':1.0,
                    'stronger_reference_reader_executed':False,'human_verified_sufficiency':False,
                    'independent_semantic_correctness':None,'hf_operator_tokenizer_parity':False,
                    'production_authorized':False}
            with self.assertRaises(ValueError):v.verify_answers(self.plan,self.src,self.rank,packet)
            packet['stronger_reference_reader_executed']=True
            with self.assertRaises(ValueError):v.verify_answers(self.plan,self.src,self.rank,packet)

if __name__=='__main__':unittest.main()
