"""Source-only denials always run; 96 original physical-journal cases optional.

For private original full recount, export HEPTA_AMCN_ORIGINAL_RECOUNT_ROOT and
HEPTA_AMCN_ORIGINAL_READER_ROOT to SHA-pinned local material; no downloads.
"""
from __future__ import annotations

import copy
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
import unittest

import amcn_original_reader_private_recount as a


class IndependentSourceContracts(unittest.TestCase):
    def test_external_file_sha_is_strict(self):
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'original.json';file.write_bytes(b'{"x":1}\n')
            actual=sha256(file.read_bytes()).hexdigest()
            self.assertEqual(a.read_exact(file,actual),file.read_bytes())
            with self.assertRaisesRegex(ValueError,'SHA pin'):
                a.read_exact(file,'0'*64)

    def test_duplicate_json_member_denied(self):
        with self.assertRaisesRegex(ValueError,'duplicate JSON member'):
            a.strict_json(b'{"x":1,"x":2}')

    def test_nan_json_denied(self):
        with self.assertRaisesRegex(ValueError,'nonfinite JSON'):
            a.strict_json(b'{"x":NaN}')

    def test_torn_jsonl_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'attempts.jsonl';file.write_bytes(b'{"status":"success"}')
            with self.assertRaisesRegex(ValueError,'torn JSONL'):
                a.jsonl(file,sha256(file.read_bytes()).hexdigest())

    def test_false_future_window_denied(self):
        plan={'profile':a.BASE_PROFILE,'production_accepted':False,
              'independent_future_windows':2,'publisher_support_not_independent_human_review':True,
              'reader_sha256':a.ORIGINAL_MODEL,'tokenizer_sha256':a.ORIGINAL_TOKENIZER,
              'max_new_tokens':24,'arms':list(a.ARMS),'cases':[]}
        with self.assertRaisesRegex(ValueError,'identity drift'):
            a.validate_plan(plan,{'cases':0},'annotation')

    def test_literal_abstention_recognizer_is_not_semantic_judge(self):
        self.assertIsNone(a.ABSTAIN.search('An arbitrary historical claim without evidence.'))
        self.assertIsNotNone(a.ABSTAIN.search('unknown'))
        self.assertIsNotNone(a.ABSTAIN.search('insufficient evidence'))

    def test_invalid_citation_is_detectable(self):
        self.assertEqual([int(x) for x in a.CITE.findall('Answer [E0] or [E123456]')],[0,123456])

    def test_model_sha_pinned_in_audit(self):
        self.assertEqual(a.ORIGINAL_MODEL,'5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c')
        self.assertEqual(len(a.PINS),3)


class OriginalArchivedJournalRecount(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root=os.environ.get('HEPTA_AMCN_ORIGINAL_RECOUNT_ROOT')
        model=os.environ.get('HEPTA_AMCN_ORIGINAL_READER_ROOT')
        if not root or not model:
            raise unittest.SkipTest('private 96 original logs and pinned tokenizer are not on CI runner')
        from amcn_original_text_reader import ArchivedByteLevelBPE
        cls.root=Path(root)
        cls.tokenizer=ArchivedByteLevelBPE(Path(model),expected_tokenizer_sha256=a.ORIGINAL_TOKENIZER)

    def test_all_original_96_recount(self):
        x=a.audit(self.root,self.tokenizer)
        self.assertEqual(x['original_attempts_recounted'],96)
        self.assertEqual(x['original_24_to_64_greedy_prefix_pairs_verified'],16)
        self.assertEqual(x['no_evidence_nonabstaining_outputs'],20)
        self.assertEqual(x['no_evidence_literal_abstention_outputs'],0)
        self.assertFalse(x['production_accepted'])

    def test_all_citation_recounts(self):
        x=a.audit(self.root,self.tokenizer)
        self.assertEqual(sum(t['answers_with_citation_tag'] for t in x['cohort_stats'].values()),27)
        self.assertEqual(sum(t['citation_tag_count'] for t in x['cohort_stats'].values()),30)
        self.assertEqual(sum(t['citation_outside_delivered_evidence'] for t in x['cohort_stats'].values()),0)

    def test_original_start_file_tamper_fails_external_sha(self):
        with tempfile.TemporaryDirectory() as folder:
            original=self.root/a.PINS['long']['dir_name']
            copied=Path(folder)/'starts.jsonl'
            copied.write_bytes((original/'starts.jsonl').read_bytes()+b'{}\n')
            with self.assertRaisesRegex(ValueError,'SHA pin'):
                a.jsonl(copied,a.PINS['long']['starts'])

    def test_original_answer_file_tamper_fails_external_sha(self):
        with tempfile.TemporaryDirectory() as folder:
            original=self.root/a.PINS['verbatim']['dir_name']
            copied=Path(folder)/'raw_answers.jsonl'
            raw=(original/'raw_answers.jsonl').read_bytes()
            copied.write_bytes(raw.replace(b'"status"',b'"status_mut"',1) if b'"status"' in raw else raw+b' ')
            with self.assertRaisesRegex(ValueError,'SHA pin'):
                a.jsonl(copied,a.PINS['verbatim']['answers'])

    def test_source_case_reordering_refused(self):
        cfg=a.PINS['annotation']
        plan=a.strict_json(a.read_exact(self.root/cfg['plan_name'],cfg['plan']))
        plan['cases']=list(reversed(plan['cases']))
        with self.assertRaisesRegex(ValueError,'original external SHA pin mismatch'):
            # Recount must first enforce exact original plan pin independently.
            with tempfile.TemporaryDirectory() as folder:
                p=Path(folder)/cfg['plan_name'];p.write_bytes(a.canonical(plan))
                a.read_exact(p,cfg['plan'])

    def test_wrong_long_reader_model_sha_rejected(self):
        cfg=a.PINS['long']
        d=self.root/cfg['dir_name']
        seal=a.strict_json(a.read_exact(d/'seal.json',cfg['seal']))
        seal['original_reader_sha256']='0'*64
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'seal.json';p.write_bytes(a.canonical(seal))
            with self.assertRaisesRegex(ValueError,'SHA pin'):
                a.read_exact(p,cfg['seal'])

    def test_private_plans_do_not_confer_human_entailment(self):
        for cohort in ('annotation','verbatim'):
            cfg=a.PINS[cohort]
            plan=a.strict_json(a.read_exact(self.root/cfg['plan_name'],cfg['plan']))
            self.assertTrue(plan['publisher_support_not_independent_human_review'])
            self.assertFalse(plan['production_accepted'])

if __name__=='__main__':unittest.main()
