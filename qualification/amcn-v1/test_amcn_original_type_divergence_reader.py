"""Original 14-case original model/source/journal integrity tests (research only)."""
from __future__ import annotations

import copy
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import amcn_original_type_divergence_reader as e


class FullOriginalTypeDisagreement(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(os.environ.get('HEPTA_AMCN_TYPE14_ORIGINAL_ROOT',
                                       '/mnt/data/amcn_e2'))
        if not (cls.root / 'type14_original_plan.json').is_file():
            raise unittest.SkipTest('needs originally sealed 14-case source/Head material')
        cls.plan = json.loads((cls.root / 'type14_original_plan.json').read_bytes())
        cls.model = Path(os.environ.get('HEPTA_AMCN_TYPE14_READER_DIR',
                                        '/mnt/data/amcn_causal/original/reader'))

    def test_registered_all_fourteen_divergences(self):
        self.assertEqual(len(e.validate_plan(self.plan)), 42)
        self.assertEqual([c['divergence_kind'] for c in self.plan['cases']].count('source_replacement'), 10)
        self.assertEqual([c['divergence_kind'] for c in self.plan['cases']].count('order_only'), 4)
        self.assertEqual(e.sha_bytes(e.canonical(self.plan)),
                         'e92c469bb8f03ae5b5c3382301244043eb4d3a4ecfbc64d4835b46f4185198c7')

    def test_registered_plans_no_equal_token_claim(self):
        self.assertFalse(any(len({c['requests'][a]['input_tokens'] for a in e.ARMS}) == 1
                             for c in self.plan['cases']))

    def test_original_only_two_source_families(self):
        self.assertEqual({c['family'] for c in self.plan['cases']}, set(e.FAMILIES))
        self.assertEqual(len([c for c in self.plan['cases'] if c['family'] == 'conv-49']), 6)
        self.assertEqual(len([c for c in self.plan['cases'] if c['family'] == 'conv-50']), 8)

    def test_no_publisher_data_in_reader_prompt_plan(self):
        self.assertNotIn('publisher_support', json.dumps(self.plan))
        self.assertNotIn('adversarial_answer', json.dumps(self.plan))
        self.assertFalse(self.plan['case_selection_from_publisher_gold'])

    def test_missing_or_reordered_registered_case_denied(self):
        r = copy.deepcopy(self.plan)
        r['cases'].pop()
        with self.assertRaises(ValueError): e.validate_plan(r)

    def test_unregistered_type_head_divergence_denied(self):
        r = copy.deepcopy(self.plan)
        r['cases'][0]['requests']['typed_equal_budget']['source_ids'] = copy.deepcopy(
            r['cases'][0]['requests']['untyped_equal_budget']['source_ids'])
        with self.assertRaises(ValueError): e.validate_plan(r)

    def test_source_changed_without_sha_denied(self):
        r = copy.deepcopy(self.plan)
        r['cases'][0]['requests']['bm25']['prompt'] += ' tampered'
        with self.assertRaisesRegex(ValueError, 'prompt'): e.validate_plan(r)

    def test_fake_future_and_model_promotion_denied(self):
        for field, value in (('production_accepted', True),
                             ('official_hf_parity_verified', True)):
            r = copy.deepcopy(self.plan)
            r[field] = value
            with self.assertRaises(ValueError): e.validate_plan(r)

    def test_missing_physical_bank_denied(self):
        data=copy.deepcopy(self.plan)
        data['original_bank_sha256'] = 'f'*64
        with self.assertRaises(ValueError): e.validate_plan(data)

    def test_seal_and_durable_original_journal_match(self):
        directory = self.root / 'original-reader-42'
        if not directory.is_dir():self.skipTest('requires original model outputs')
        seal = json.loads((directory / 'seal.json').read_bytes())
        tok = e.ArchivedByteLevelBPE(self.model, expected_tokenizer_sha256=e.TOKENIZER_SHA)
        responses, failures = e.verify_original_seal(self.plan, directory, seal, tok)
        self.assertEqual(len(responses), 42)
        self.assertEqual(failures, 0)
        self.assertEqual(seal['successful_original_reader_calls'], 42)

    def test_changed_original_token_ids_and_rehashed_journal_denied(self):
        directory = self.root / 'original-reader-42'
        if not directory.is_dir():self.skipTest('requires original model outputs')
        seal = json.loads((directory / 'seal.json').read_bytes())
        tok = e.ArchivedByteLevelBPE(self.model, expected_tokenizer_sha256=e.TOKENIZER_SHA)
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            (folder / 'starts.jsonl').write_bytes((directory / 'starts.jsonl').read_bytes())
            rows = e.read_jsonl(directory / 'raw_answers.jsonl')
            rows[0]['raw_model_text'] += ' foreign-result'
            rows[0]['raw_model_text_sha256'] = e.sha_text(rows[0]['raw_model_text'])
            (folder / 'raw_answers.jsonl').write_bytes(b''.join(e.canonical(row) for row in rows))
            rewritten = copy.deepcopy(seal)
            rewritten['answer_journal_sha256'] = e.file_sha(folder / 'raw_answers.jsonl')
            with self.assertRaisesRegex(ValueError, 'model result altered'):
                e.verify_original_seal(self.plan, folder, rewritten, tok)

    def test_lost_failed_attempt_cannot_be_declared_complete(self):
        directory = self.root / 'original-reader-42'
        if not directory.is_dir():self.skipTest('requires original model outputs')
        seal = json.loads((directory / 'seal.json').read_bytes())
        tok = e.ArchivedByteLevelBPE(self.model, expected_tokenizer_sha256=e.TOKENIZER_SHA)
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            starts = e.read_jsonl(directory / 'starts.jsonl')
            (folder / 'starts.jsonl').write_bytes(b''.join(e.canonical(x) for x in starts[:-1]))
            (folder / 'raw_answers.jsonl').write_bytes((directory / 'raw_answers.jsonl').read_bytes())
            modified = copy.deepcopy(seal)
            modified['start_journal_sha256'] = e.file_sha(folder / 'starts.jsonl')
            with self.assertRaises(ValueError):
                e.verify_original_seal(self.plan, folder, modified, tok)

    def test_original_postseal_measured_negative(self):
        p = self.root / 'type14_postsealed_score.json'
        if not p.exists():self.skipTest('requires independently scored original model outputs')
        report = json.loads(p.read_bytes())
        self.assertEqual(report['original_reader_calls'],42)
        self.assertEqual({arm:report['arm_totals'][arm]['weak_any_at3'] for arm in e.ARMS},
                         {'bm25':5,'untyped_equal_budget':7,'typed_equal_budget':7})
        self.assertEqual({arm:report['arm_totals'][arm]['strict_literal_answer_match'] for arm in e.ARMS},
                         dict.fromkeys(e.ARMS,0))
        self.assertEqual(report['type_different_raw_text_question_count'],11)
        self.assertFalse(report['identical_observed_input_tokens'])
        self.assertFalse(report['production_accepted'])
        self.assertFalse(report['independent_semantic_entailment_verified'])

    def test_create_only_source_seal(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'packet.json'
            e.create_once(p, {'x':17})
            with self.assertRaisesRegex(ValueError,'overwriting'):
                e.create_once(p, {'x':18})


if __name__ == '__main__': unittest.main()
