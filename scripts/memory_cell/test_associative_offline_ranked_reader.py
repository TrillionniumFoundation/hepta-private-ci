"""No-model tests for the independent 100-arm offline Reader accounting."""
import tempfile
import json
from pathlib import Path
import os
import unittest
from associative_question_conditioned import reader_inputs
from associative_offline_ranked_reader import review, READ_SCHEMA
from associative_locomo_shadow import exclusive

ROOT=Path(os.environ.get('HEPTA_OFFLINE_RANKED_FIXTURE', '/nonexistent-offline-ranked-fixture'))
V2=Path(os.environ.get('HEPTA_OFFLINE_V2_PLAN', '/nonexistent-offline-v2-plan')) / 'plan.json'
SOURCE=Path(os.environ.get('HEPTA_OFFLINE_ORIGINAL_DATASET', '/nonexistent-original'))

@unittest.skipUnless((ROOT / "public/public.json").is_file() and V2.is_file() and SOURCE.is_file(), "sealed ranked fixture not staged")
class RankedReaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs=list(reader_inputs(ROOT/'public',ROOT/'rank',per_family=2))
    def test_true_fixed_100_census_without_answers(self):
        self.assertEqual(len(self.inputs),100)
        self.assertEqual(len({x['question_id'] for x in self.inputs}),20)
        self.assertEqual({x['arm'] for x in self.inputs},
             {'empty','bm25','rrf','question_conditioned','rrf_question_conditioned'})
        self.assertTrue(all(len(x['evidence'])==0 for x in self.inputs if x['arm']=='empty'))
    def test_fixed_questions_equal_privileged_plan(self):
        premise=json.loads(V2.read_text())
        self.assertEqual({x['question_id'] for x in self.inputs},
                         {x['question_id'] for x in premise['entries']})
    def test_evidence_sources_remain_bounded_to_public(self):
        public=json.loads((ROOT/'public/public.json').read_text())
        sources={g['family']:{s['id'] for s in g['sources']} for g in public['families']}
        self.assertTrue(all({e['source_id'] for e in x['evidence']}<=sources[x['family']]
                            for x in self.inputs))
    def test_missing_output_is_not_success(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            exclusive(p/'reader-journal.json',[])
            exclusive(p/'reader-seal.json',dict(schema=READ_SCHEMA,planned=100))
            with self.assertRaisesRegex(ValueError,'unsealed'):
                review(ROOT/'public',ROOT/'rank',p,SOURCE,p/'review.json')
    def test_wrong_evidence_is_not_rebound_as_correct(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            rows=[dict(question_id=e['question_id'],family=e['family'],arm=e['arm'],
                       evidence_ids=[s['source_id'] for s in e['evidence']],
                       result=dict(status='failed',answer=None)) for e in self.inputs]
            rows[0]['evidence_ids']=['D999:999']
            sha=exclusive(p/'reader-journal.json',rows)
            rank=json.loads((ROOT/'rank/seal.json').read_text());public=json.loads((ROOT/'public/manifest.json').read_text())
            exclusive(p/'reader-seal.json',dict(schema=READ_SCHEMA,planned=100,
                reader_journal_sha256=sha,ranked_journal_sha256=rank['journal_sha256'],
                public_sha256=public['public_sha256'],official_reader_parity_certified=False,
                gold_reference_visible=False,production_accepted=False))
            with self.assertRaisesRegex(ValueError,'evidence hash/identity changed'):
                review(ROOT/'public',ROOT/'rank',p,SOURCE,p/'review.json')
if __name__=='__main__':unittest.main()
