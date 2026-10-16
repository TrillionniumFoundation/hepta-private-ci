"""Offline Reader boundary tests; mocks prove mechanics, NOT task benefit."""
from pathlib import Path
import os
import json
import tempfile
import unittest
from unittest.mock import patch

import associative_offline_reader_diagnostic as d
from associative_locomo_shadow import canonical, exclusive, strict_json

ROOT = Path(os.environ.get('HEPTA_OFFLINE_PREMISE_FIXTURE', '/nonexistent-offline-premise-fixture'))

class StubTokenizer:
    def __init__(self, bad=False, large=False):
        self.bad=bad; self.large=large; self.messages=None
    def render(self,messages):
        self.messages=messages
        if self.bad:raise ValueError('model token injection')
        return json.dumps(messages)
    def encode(self,text):
        return list(range(2060)) if self.large else [1,2,3,4]
    def decode(self,ids):
        return 'the observed answer [E1]'
class StubModel:
    def __init__(self,bad=False,large=False):
        self.tokenizer=StubTokenizer(bad,large);self.budget=None
    def generate(self,ids,maximum):
        self.budget=maximum
        return [3,4]

@unittest.skipUnless((ROOT / "v2plan/plan.json").is_file(), "sealed premise fixture not staged")
class LocalReaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan,cls.seal=d.read_plan(ROOT/'v2plan')
        cls.first=cls.plan['entries'][0]
    def test_real_plan_is_complete_and_answer_free(self):
        self.assertEqual(len(self.plan['entries']),40)
        self.assertEqual(len(set(e['question_id'] for e in self.plan['entries'])),20)
        self.assertFalse(self.plan['raw_gold_answers_included'])
        self.assertEqual(self.plan['recovered_source_ids'],['D22:12','D23:15'])
    def test_only_question_and_evidence_enter_model(self):
        model=StubModel()
        obs=d.strict_offline_result(model,self.first)
        self.assertEqual(obs['status'],'succeeded')
        self.assertEqual(model.budget,48)
        self.assertEqual(model.tokenizer.messages[0]['content'],d.SYSTEM)
        body=json.loads(model.tokenizer.messages[1]['content'])
        self.assertEqual(set(body),{'question','evidence'})
        self.assertEqual(body['question'],self.first['question'])
        self.assertTrue(all(set(e)=={'label','text'} for e in body['evidence']))
        self.assertNotIn('gold',model.tokenizer.messages[1]['content'])
    def test_bounds_abort_before_model_call(self):
        model=StubModel(large=True)
        obs=d.strict_offline_result(model,self.first)
        self.assertEqual(obs['status'],'unavailable')
        self.assertIsNone(model.budget)
    def test_special_token_rejected_instead_of_sanitized(self):
        model=StubModel(bad=True)
        obs=d.strict_offline_result(model,self.first)
        self.assertEqual(obs['status'],'failed')
        self.assertEqual(obs['reason'],'ValueError')
    def test_seal_cannot_rewrite_plan(self):
        with tempfile.TemporaryDirectory() as temp:
            src=Path(temp)
            (src/'plan.json').write_bytes((ROOT/'v2plan/plan.json').read_bytes()+b' ')
            (src/'seal.json').write_bytes((ROOT/'v2plan/seal.json').read_bytes())
            with self.assertRaisesRegex(ValueError,'unsealed'):
                d.read_plan(src)
    def test_review_fails_for_incomplete_census(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            rows=[dict(question_id=self.first['question_id'],family=self.first['family'],
                       arm=self.first['arm'],evidence_ids=[],result=dict(status='failed',answer=None))]
            stamp=exclusive(folder/'reader-journal.json',rows)
            exclusive(folder/'reader-seal.json',dict(schema=d.READER_SCHEMA,plan_sha256=self.seal['plan_sha256'],
                        reader_journal_sha256=stamp,planned=1,complete_original_40_attempt_census=False,
                        same_as_hf_reference_reader_verified=False,production_accepted=False))
            with self.assertRaisesRegex(ValueError,'incomplete'):
                d.postseal_review(ROOT/'v2plan',folder,ROOT/'locomo.json',folder/'review.json')
    def test_review_fails_on_source_id_change_even_when_journal_resealed(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            rows=[dict(question_id=e['question_id'],family=e['family'],arm=e['arm'],
                evidence_ids=[s['source_id'] for s in e['evidence']],
                result=dict(status='failed',reason='test-only',answer=None)) for e in self.plan['entries']]
            rows[0]['evidence_ids']=['D123:999']
            j=exclusive(folder/'reader-journal.json',rows)
            exclusive(folder/'reader-seal.json',dict(schema=d.READER_SCHEMA,plan_sha256=self.seal['plan_sha256'],
                reader_journal_sha256=j,planned=40,complete_original_40_attempt_census=True,
                same_as_hf_reference_reader_verified=False,production_accepted=False))
            with self.assertRaisesRegex(ValueError,'evidence changed'):
                d.postseal_review(ROOT/'v2plan',folder,ROOT/'locomo.json',folder/'review.json')
    def test_review_fails_for_missing_or_extra_answer_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            rows=[dict(question_id=e['question_id'],family=e['family'],arm=e['arm'],
                evidence_ids=[s['source_id'] for s in e['evidence']],
                result=dict(status='failed',reason='mechanics-only',answer=None)) for e in self.plan['entries']]
            rows[0]['result']={'status':'succeeded','answer':''}
            j=exclusive(folder/'reader-journal.json',rows)
            exclusive(folder/'reader-seal.json',dict(schema=d.READER_SCHEMA,plan_sha256=self.seal['plan_sha256'],
                reader_journal_sha256=j,planned=40,complete_original_40_attempt_census=True,
                same_as_hf_reference_reader_verified=False,production_accepted=False))
            with self.assertRaisesRegex(ValueError,'missing answer text'):
                d.postseal_review(ROOT/'v2plan',folder,ROOT/'locomo.json',folder/'review.json')

if __name__=='__main__':unittest.main()
