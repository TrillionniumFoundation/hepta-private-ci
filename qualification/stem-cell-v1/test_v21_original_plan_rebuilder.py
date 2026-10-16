"""Source-only negative contracts. Fixtures never claim original 135M/Qwen forwards."""
from __future__ import annotations
from collections import Counter
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import v21_original_plan_rebuilder as p


def toy_source():
    docs=[{'id':str(n),'text':t} for n,t in enumerate((
        'Alice visited Berlin with Bob','Bob works in Stockholm',
        'carrots taste sweet', 'Alice visited Helsinki twice',
        'Mary lives in Oslo', 'Alice and Bob met last year',
        *[f'some unrelated scene {i}' for i in range(26)]))]
    return docs

class RebuildContracts(unittest.TestCase):
    def test_frozen_hashes_are_public_historical_values(self):
        self.assertEqual(p.SOURCE_SHA,'9d707c297dc743cffe00d94ead04198b7039f72027743dc6d6e02c826a623a8c')
        self.assertEqual(p.BM25_RANK_SHA,'b0b38675d2d5458795d0577d5c861b796dfbdf9e7d4cd089838895c419831697')
        self.assertEqual(p.V16_PLAN_SHA,'26a4d5a4883c98d61d9405f739dda7e49f433370c30290275f0f04441d7067c8')
    def test_real_bm25_sees_exact_source_terms(self):
        scores=p.BM25(toy_source()).top32('Who visited Berlin with Bob?')
        self.assertEqual(len(scores),32)
        self.assertEqual(len(set(scores)),32)
        self.assertEqual(scores[0],'0')
    def test_source_order_is_deterministic(self):
        docs=toy_source()
        first=p.BM25(docs).top32('completely unheard question')
        second=p.BM25(copy.deepcopy(docs)).top32('completely unheard question')
        self.assertEqual(first,second)
    def test_empty_query_denied(self):
        with self.assertRaises(ValueError):p.BM25(toy_source()).top32('  ')
    def test_missing_passages_denied(self):
        with self.assertRaises(ValueError):p.BM25(toy_source()[:31])
    def test_no_foreign_evidence_prompt(self):
        with self.assertRaises(ValueError):p.prompt('x',['missing'],{})
    def test_duplicate_evidence_id_denied(self):
        with self.assertRaises(ValueError):p.prompt('x',['a','a'],{'a':'text'})
    def test_no_extra_evidence(self):
        with self.assertRaises(ValueError):p.prompt('x',['a','b','c','d'],{x:'text' for x in 'abcd'})
    def test_exact_original_prompt_order(self):
        out=p.prompt('Who?',['a','b'],{'a':'Alice','b':'Bob'})
        self.assertIn('Question: Who?\n[E1] Alice\n[E2] Bob\n',out)
        self.assertEqual(out.count('<|im_start|>'),3)
    def test_censored_gold_is_not_literal(self):
        for answer in (None,False,3,'','yes','unknown'):
            with self.subTest(answer=answer):
                self.assertFalse(p._literal({'answer':answer},'yes, unknown'))
    def test_publisher_answer_literal_is_only_selection_proxy(self):
        self.assertTrue(p._literal({'answer':'Stockholm'},'I moved to Stockholm'))
    def test_invalid_json_duplicate_key(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'not-original.json'
            f.write_text('{"a":1,"a":2}')
            with self.assertRaises(ValueError):p.read_original(f)
    def test_fail_closed_missing_raw_corpus(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'fake.json';f.write_text('[]')
            with self.assertRaises(ValueError):p.read_original(f)
    def test_fail_closed_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            a=Path(d)/'a.json';a.write_text('[]')
            b=Path(d)/'b.json';b.symlink_to(a)
            with self.assertRaises(ValueError):p.read_original(b)
    def test_source_wrong_roots_denied(self):
        with self.assertRaises(ValueError):p.source_only([])
    def test_source_bad_sample_denied(self):
        with self.assertRaises(ValueError):p.source_only([{'sample_id':'other'}]*10)
    def test_public_receipt_no_self_promotion(self):
        original={
            'schema':p.SCHEMA,'sha256_original_corpus':p.CORPUS_SHA,
            'sha256_source_only':p.SOURCE_SHA,'sha256_rank_rows':p.BM25_RANK_SHA,
            'sha256_private_routes':p.PRIVATE_ROUTE_SHA,'sha256_v16_plan':p.V16_PLAN_SHA,
            'original_family_count':10,'source_turn_count':5882,'question_count':1986,
            'historical_roots':4,'original_v16_questions':32,'reference_requests_prepared':128,
            'reader_model_forwards_executed':0,'reference_model_forwards_executed':0,
            'publisher_answer_dependent_historical_selection':True,
            'human_verified_sufficiency':False,'independent_semantic_correctness':None,
            'production_authorized':False,'decision':'SOURCE_RECONSTRUCTION_ONLY_HOLD_NO_GO',
        }
        self.assertFalse(p.verify_public_receipt(original)['production_authorized'])
        for key,value in (
            ('reference_model_forwards_executed',128),('reader_model_forwards_executed',128),
            ('human_verified_sufficiency',True),('production_authorized',True),
            ('independent_semantic_correctness',1.0),('historical_roots',32),
            ('sha256_v16_plan','0'*64),('private_original_questions',['secret']),
        ):
            corrupted=copy.deepcopy(original);corrupted[key]=value
            with self.subTest(key=key), self.assertRaises(ValueError):
                p.verify_public_receipt(corrupted)
    def test_public_receipt_does_not_accept_bool_int(self):
        valid={
            'schema':p.SCHEMA,'sha256_original_corpus':p.CORPUS_SHA,
            'sha256_source_only':p.SOURCE_SHA,'sha256_rank_rows':p.BM25_RANK_SHA,
            'sha256_private_routes':p.PRIVATE_ROUTE_SHA,'sha256_v16_plan':p.V16_PLAN_SHA,
            'original_family_count':10,'source_turn_count':5882,'question_count':1986,
            'historical_roots':4,'original_v16_questions':32,'reference_requests_prepared':128,
            'reader_model_forwards_executed':0,'reference_model_forwards_executed':0,
            'publisher_answer_dependent_historical_selection':True,
            'human_verified_sufficiency':False,'independent_semantic_correctness':None,
            'production_authorized':False,'decision':'SOURCE_RECONSTRUCTION_ONLY_HOLD_NO_GO'}
        for key in ['original_family_count','reader_model_forwards_executed']:
            changed=dict(valid);changed[key]=False
            with self.assertRaises(ValueError):p.verify_public_receipt(changed)

if __name__=='__main__':unittest.main()
