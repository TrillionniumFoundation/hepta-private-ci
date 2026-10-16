"""Strict post-seal audit and negative reference controls; not model evidence."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from associative_offline_reader_compare import _score, _rows, SCHEMA, audit
from associative_locomo_shadow import exclusive
from associative_offline_ranked_reader import READ_SCHEMA

class PureAuditTests(unittest.TestCase):
    def source(self):return {'conv-1':{'qa':[{'answer':'alpha'}]}}
    def controls(self):return [dict(question_id='conv-1/q0000',family='conv-1',arm='bm25',evidence=[dict(label='E1',source_id='D1:1')])]
    def observed(self,answer,ids=['D1:1']):
        return [dict(question_id='conv-1/q0000',family='conv-1',arm='bm25',evidence_ids=ids,
                     result=dict(status='succeeded',answer=answer))]
    def test_gold_not_used_for_generation_and_citation_marker_counted_as_structure(self):
        v=_score(self.observed('alpha [E1]'),self.controls(),self.source())['by_arm']['bm25']
        self.assertGreater(v['mean_token_f1'],0)
        self.assertEqual(v['citation']['markers'],1)
        self.assertEqual(v['citation']['valid_source_labels'],1)
    def test_forged_citation_is_not_semantic_entailment(self):
        v=_score(self.observed('alpha [E99]'),self.controls(),self.source())['by_arm']['bm25']
        self.assertEqual(v['citation']['markers'],1)
        self.assertEqual(v['citation']['valid_source_labels'],0)
    def test_change_to_delivered_source_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'evidence source identity changed'):
            _score(self.observed('alpha',['D999:1']),self.controls(),self.source())
    def test_duplicate_attempt_rejected(self):
        with self.assertRaisesRegex(ValueError,'missing or duplicate'):
            _score(self.observed('alpha')*2,self.controls(),self.source())
    def test_seal_tamper_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)
            actual=exclusive(p/'reader-journal.json',[])
            exclusive(p/'reader-seal.json',dict(schema=READ_SCHEMA,reader_journal_sha256=actual,
                 ranked_journal_sha256='abc',planned=100,production_accepted=False))
            with (p/'reader-journal.json').open('ab') as f:f.write(b' ')
            with self.assertRaisesRegex(ValueError,'sealed'):
                _rows(p,READ_SCHEMA,'ranked_journal_sha256','abc',100)

DATA=Path(os.getenv('HEPTA_OFFLINE_READER_DATA','/nonexistent-research-data'))
@unittest.skipUnless((DATA/'consolidated-audit.json').is_file(),'real sealed research bundle not supplied')
class OriginalResultAuditTests(unittest.TestCase):
    def test_140_actual_attempts_and_10_source_groups(self):
        d=json.loads((DATA/'consolidated-audit.json').read_text())
        self.assertEqual(d['schema'],SCHEMA)
        self.assertEqual(d['actual_offline_frozen_weight_reader_attempts'],140)
        self.assertEqual(d['source_groups'],10)
        self.assertFalse(d['official_transformers_bf16_equivalence_certified'])
    def test_empty_and_parametric_controls_remain_visible(self):
        d=json.loads((DATA/'consolidated-audit.json').read_text())
        self.assertEqual(d['ranked_reader']['by_arm']['empty']['planned'],20)
        self.assertFalse(d['memorycell_superiority_claim'])
        self.assertEqual(d['ranked_reader']['by_arm']['rrf']['citation']['markers'],0)

if __name__=='__main__':unittest.main()
