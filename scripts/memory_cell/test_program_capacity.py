"""Fail-closed tests for original-weight Reader study and independent scoring.

These tests replay the sealed actual original journals, NOT mocked model success.
They are a protocol check and do not establish reference HF parity.
"""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
import sys
import torch

from physical_original_reader import ReaderTokenizer, ReaderModel, digest, filehash, ORIGINAL_LOGITS_SHA
import study_program_capacity as stage1
import study_format_intervention_v2 as stage2

BASE=Path(__file__).resolve().parent
SRC=Path(os.environ.get('MEMORY_ORIGINAL_HTTP_MODULE','/mnt/data/memory-next5/pinned_original_http_client.py'))
TESTS=Path(os.environ.get('MEMORY_ORIGINAL_HTTP_TESTS','/mnt/data/memory-next5/pinned_original_test_httplib.py'))
MODEL=Path(os.environ.get('MEMORY_ORIGINAL_READER_STAGE','/mnt/data/real_reader_stage'))
V1=Path(os.environ.get('MEMORY_READER_V1_JOURNAL',str(BASE/'actual-reader-journals/original-generation.jsonl')))
V2=Path(os.environ.get('MEMORY_READER_V2_JOURNAL',str(BASE/'v2-actual-reader-journals/original-generation.jsonl')))

class OriginalProgramReaderTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.plan=stage1.build_plan(SRC,TESTS)
  cls.proto=stage2.protocol(digest(stage1.CANON(cls.plan)))
  cls.j1=filehash(V1);cls.j2=filehash(V2)
  cls.verified1=stage1.score(cls.plan,V1,SRC,TESTS,cls.j1)
  cls.verified2=stage2.rescore(cls.plan,cls.proto,V2,SRC,TESTS,MODEL,cls.j2)

 def test_original_genuine_model_weights_pinned(self):
  self.assertEqual(filehash(MODEL/'model.safetensors'),stage1.WEIGHT_SHA)
  self.assertEqual(filehash(MODEL/'tokenizer.json'),stage1.TOKENIZER_SHA)

 def test_original_source_preparation_sha(self):
  self.assertEqual(digest(stage1.CANON(self.plan)),'bb4a7ca16425f6a8072287f225893cf2d1ea5a13897206cf48b39e44db60ab74')
  self.assertTrue(stage1.verify_plan(self.plan,SRC,TESTS))

 def test_v2_protocol_sha_before_generation(self):
  self.assertEqual(digest(stage1.CANON(self.proto)),'8761735110a0bfb23dec7a7bd6acdf09c3bf5e3e38d1dcdc246bafe5a58aaf10')
  self.assertIn('unknown',self.proto['frozen_system_prompt'])

 def test_original_eight_model_calls_per_version(self):
  self.assertEqual(len(V1.read_bytes().splitlines()),8)
  self.assertEqual(len(V2.read_bytes().splitlines()),8)
  self.assertEqual(sum(x['model_calls'] for x in self.verified1['by_condition'].values()),8)
  self.assertEqual(self.verified2['actual_model_calls'],8)

 def test_strict_task_null_both_protocols(self):
  for result in (self.verified1,self.verified2):
   self.assertEqual([result['by_condition'][a]['strict_correct'] for a in stage1.CONDS] if result==self.verified1 else [result['by_condition'][a]['strict_correct'] for a in stage1.CONDS],[0,0,0,0])

 def test_source_order_and_evidence_bound(self):
  for case in self.plan['cases']:
   self.assertEqual(set(case['conditions']),set(stage1.CONDS))
   self.assertLessEqual(len(case['conditions']['lexical_top2']),2)
   self.assertEqual(len(case['conditions']['declaration_lesion']),2)

 def test_lesion_preserves_sources_but_drops_declaration(self):
  for c,target in zip(self.plan['cases'],[x[2] for x in stage1.TASKS]):
   o=c['conditions']['original_crossfile_oracle']
   les=c['conditions']['declaration_lesion']
   self.assertEqual([x['kind'] for x in o],[x['kind'] for x in les])
   self.assertTrue(any('def '+target in x['text'] for x in o))
   self.assertFalse(any('def '+target in x['text'] for x in les))

 def test_no_gold_in_reader_plan(self):
  for c in self.plan['cases']:
   self.assertFalse(any(k in c for k in ('gold','expected_answer','target_symbol','label')))

 def test_no_pretrained_parity_promotion(self):
  self.assertFalse(self.verified2['exact_pretrained_reference_parity_unverified']==False)
  self.assertFalse(self.verified1['official_HF_parity_certified'])
  self.assertFalse(self.verified1['production_qualified'])

 def test_genuine_original_logits_topfive(self):
  torch.set_num_threads(3)
  model=ReaderModel(MODEL)
  logits=model.forward([1,420,35,177],reset=True)
  self.assertEqual(torch.topk(logits,5).indices.tolist(),[122,123,237,113,133])
  self.assertNotEqual(digest(logits.contiguous().numpy().tobytes()),ORIGINAL_LOGITS_SHA)

 def test_v2_output_token_ids_automatically_redecoded(self):
  rows=[json.loads(x) for x in V2.read_bytes().splitlines()]
  tokenizer=ReaderTokenizer(MODEL/'tokenizer.json')
  for row in rows:self.assertEqual(tokenizer.decode(row['output_token_ids']),row['answer'])

 def test_missing_journal_row_rejected(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'a.jsonl';p.write_bytes(b'\n'.join(V2.read_bytes().splitlines()[:7])+b'\n')
   with self.assertRaisesRegex(ValueError,'incomplete original model census'):
    stage2.rescore(self.plan,self.proto,p,SRC,TESTS,MODEL,filehash(p))

 def test_modified_answer_bytes_rejected(self):
  records=[json.loads(x) for x in V2.read_bytes().splitlines()];records[1]['answer']='fake'
  self.reject_rows(records,'changed original answer bytes')

 def test_modified_token_ids_rejected(self):
  records=[json.loads(x) for x in V2.read_bytes().splitlines()];records[1]['output_token_ids'][0]=999999
  self.reject_rows(records,'wrong raw token ids')

 def test_modified_input_token_digests_rejected(self):
  records=[json.loads(x) for x in V2.read_bytes().splitlines()];records[0]['input_token_digest']='0'*64
  self.reject_rows(records,'unbound original request or model')

 def test_swapped_weight_hash_rejected(self):
  records=[json.loads(x) for x in V2.read_bytes().splitlines()];records[1]['model_sha256']='0'*64
  self.reject_rows(records,'unbound original request or model')

 def test_wrong_prompt_profile_rejected(self):
  altered=dict(self.proto);altered['frozen_system_prompt']='Use the label.'
  with self.assertRaisesRegex(ValueError,'wrong v2 prompt profile'):
   stage2.rescore(self.plan,altered,V2,SRC,TESTS,MODEL,self.j2)

 def test_duplicate_original_attempt_rejected(self):
  records=[json.loads(x) for x in V2.read_bytes().splitlines()];records[1]=records[0]
  self.reject_rows(records,'duplicate Reader journal')

 def test_lesion_cannot_earn_supported_success(self):
  # Even a synthetic perfect identifier guess cannot create a removed original declaration.
  c=self.plan['cases'][0]; ev=c['conditions']['declaration_lesion']
  self.assertFalse(any(x.get('symbol')=='putheader' and 'def putheader' in x['text'] for x in ev))
  self.assertEqual(self.verified2['by_condition']['declaration_lesion']['correct_and_supported'],0)

 def test_wrong_source_rejected(self):
  with tempfile.TemporaryDirectory() as td:
   fake=Path(td)/'source.py';fake.write_bytes(SRC.read_bytes()+b'\n# changed')
   with self.assertRaisesRegex(ValueError,'original SHA-pinned Git evidence'):
    stage1.verify_plan(self.plan,fake,TESTS)

 def test_wrong_scorer_sha_rejected(self):
  with self.assertRaisesRegex(ValueError,'post-hoc raw answer alteration'):
   stage2.rescore(self.plan,self.proto,V2,SRC,TESTS,MODEL,'0'*64)

 def test_duplicate_json_field_rejected_even_if_rehashed(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'duplicate.jsonl'
   rows=V2.read_bytes().splitlines()
   p.write_bytes(rows[0].replace(b'{',b'{"status":"succeeded",',1)+b'\n'+b'\n'.join(rows[1:])+b'\n')
   with self.assertRaisesRegex(ValueError,'duplicate original JSON field'):
    stage2.rescore(self.plan,self.proto,p,SRC,TESTS,MODEL,filehash(p))

 def test_nonfinite_execution_time_rejected(self):
  records=[json.loads(x) for x in V2.read_bytes().splitlines()]
  records[0]['inference_seconds']=-1.0
  self.reject_rows(records,'invalid model execution timing')

 def test_v2_uncited_correct_not_promoted(self):
  for r in self.verified2['original_rows']:
   self.assertFalse(r['correct_and_supported'] and not r['cited_necessary_declaration'])

 def test_unknown_is_not_fabricated(self):
  self.assertEqual(sum(r['unknown_abstentions'] for r in self.verified2['by_condition'].values()),0)

 def test_cost_fields_nullable(self):
  self.assertIsNone(self.verified2['complete_lifecycle_tco'])
  self.assertIsNone(self.verified1['full_lifecycle_cost'])
  self.assertIsNone(self.verified2['real_program_repair_success'])

 def reject_rows(self,records,reason):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'tampered.jsonl'
   p.write_bytes(b''.join(stage1.CANON(x) for x in records))
   with self.assertRaisesRegex(ValueError,reason):
    stage2.rescore(self.plan,self.proto,p,SRC,TESTS,MODEL,filehash(p))

if __name__=='__main__':unittest.main()
