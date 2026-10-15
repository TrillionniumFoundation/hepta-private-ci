"""Actual archival LoCoMo E3 source + physical owner + Reader boundary contracts.

Requires exact already generated original material in HEPTA_AMCN_E3_ROOT.
Mock-free original evidence tamper tests; separate genuine Torch mechanism test.
"""
from __future__ import annotations

import copy
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import amcn_original_temporal_e3 as e
import amcn_original_temporal_e3_reader as r


class OriginalTemporalGraphTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(os.environ.get('HEPTA_AMCN_E3_ROOT', '/mnt/data/amcn_e3_work'))
        files=['public-original.json','original-train-only.json','original-withheld.json',
               'original-physical-weights.json','original-all-1986-ranks.json',
               'original-E3-postseal-score.json','original-e3-reader-plan-6.json',
               'original-e3-reader-postseal-score-v2.json']
        if not all((cls.root/f).is_file() for f in files):
            raise unittest.SkipTest('requires complete real original LoCoMo E3 material')
        cls.public=json.loads((cls.root/'public-original.json').read_bytes())
        cls.train=json.loads((cls.root/'original-train-only.json').read_bytes())
        cls.heldout=json.loads((cls.root/'original-withheld.json').read_bytes())
        cls.weights=json.loads((cls.root/'original-physical-weights.json').read_bytes())
        cls.ranks=json.loads((cls.root/'original-all-1986-ranks.json').read_bytes())
        cls.scored=json.loads((cls.root/'original-E3-postseal-score.json').read_bytes())
        cls.plan=json.loads((cls.root/'original-e3-reader-plan-6.json').read_bytes())
        cls.reader_report=json.loads((cls.root/'original-e3-reader-postseal-score-v2.json').read_bytes())

    def test_original_1986_question_5882_source_10_family_census(self):
        self.assertEqual(len(self.public['cases']),1986)
        self.assertEqual(sum(len(s) for s in self.public['sources'].values()),5882)
        self.assertEqual(set(self.public['sources']),set(e.SPLITS))
        self.assertEqual(len(self.ranks['predictions']),1986)
        self.assertEqual(len({p['case_id'] for p in self.ranks['predictions']}),1986)

    def test_preparation_isolation_six_training_roots_no_retrospective_gold(self):
        self.assertTrue(self.public['gold_included'] is False)
        self.assertTrue(self.train['heldout_gold_included'] is False)
        self.assertEqual(len(self.train['targets']),1157)
        self.assertEqual(len(self.heldout['targets']),829)
        self.assertEqual({p['family'] for p in self.train['targets']},
                         {f for f,s in e.SPLITS.items() if s=='train'})
        self.assertEqual({p['family'] for p in self.heldout['targets']},
                         {f for f,s in e.SPLITS.items() if s!='train'})
        self.assertNotIn('publisher_support',json.dumps(self.public))
        self.assertNotIn('publisher_support',json.dumps(self.ranks))

    def test_original_trained_numeric_sgd_and_physical_negative_receipt(self):
        self.assertEqual(self.weights['training_examples'],3505)
        self.assertEqual(self.weights['train_positive'],701)
        self.assertEqual(self.weights['train_negative'],2804)
        self.assertEqual(self.weights['training_families'],sorted(
            f for f in e.SPLITS if e.SPLITS[f]=='train'))
        self.assertEqual(self.weights['parameters'],6)
        self.assertTrue(self.weights['calibrated_against_independent_scalar_sgd'])
        self.assertLess(self.weights['weights']['temporal'],0)
        self.assertLess(self.weights['weights']['associative'],0)
        self.assertFalse(self.weights['relation_truth_independently_authenticated'])

    def test_unmodified_frozen_model_no_fake_trainable_graph_truth(self):
        self.assertFalse(self.weights['production_accepted'])
        self.assertFalse(self.weights['new_encoder_training'])
        self.assertEqual(self.weights['reader_calls'],0)
        self.assertFalse(self.ranks['ranking_publisher_gold_opened'])
        self.assertFalse(self.ranks['semantic_entailment_independently_verified'])

    def test_real_ten_family_graph_edges_bind_exact_unchanged_source(self):
        for f in e.SPLITS:
            sources=self.public['sources'][f]
            by={s['id']:s for s in sources}
            for edge in self.public['edges'][f]:
                self.assertIn(edge['relation'],('temporal','associative'))
                self.assertEqual(edge['support_sha256'],e.source_edge(
                    edge['source_id'],edge['target_id'],edge['relation'],by)['support_sha256'])
                self.assertEqual(by[edge['source_id']]['root'],f)

    def test_original_full_graph_rank_finishes_at_three_source_slots(self):
        self.assertEqual(self.ranks['max_final_evidence_count'],3)
        self.assertEqual(self.ranks['reader_calls'],0)
        for row in self.ranks['predictions']:
            self.assertEqual(set(row['selected']),set(e.ARMS))
            for selected in row['selected'].values():
                self.assertEqual(len(selected),3)
                self.assertEqual(len(set(selected)),3)
                self.assertTrue(set(selected)<={r['id'] for r in self.public['sources'][row['family']]})

    def test_retrospective_all_four_arm_weak_metric_negative(self):
        expected={'bm25':(174,149),'temporal_fixed':(177,152),
                  'temporal_learned':(171,145),'temporal_edge_lesion':(171,145)}
        self.assertEqual(self.scored['heldout_total'],400)
        self.assertEqual(self.scored['independent_historical_source_roots'],2)
        for a,(hit,all_hit) in expected.items():
            self.assertEqual(self.scored['totals'][a]['hit3'],hit)
            self.assertEqual(self.scored['totals'][a]['all3'],all_hit)
            self.assertEqual(self.scored['totals'][a]['questions'],400)
        self.assertIsNone(self.scored['independent_semantic_score'])
        self.assertFalse(self.scored['strong_rag_equal_compute_verified'])

    def test_original_reader_24_calls_journal_cross_recountexact(self):
        _,answers=r.recount(self.plan,self.root/'reader',self.root/'original-e3-reader-24')
        self.assertEqual(len(answers),24)
        self.assertTrue(all(row['status']=='success' for row in answers))
        self.assertEqual(self.reader_report['original_reader_attempts'],24)
        self.assertEqual(self.reader_report['original_reader_failures'],0)
        self.assertEqual(self.reader_report['original_cases_with_equal_four_arm_input_tokens'],5)

    def test_reader_weak_outcomes_no_text_accuracy_claim(self):
        for arm in e.ARMS:
            v=self.reader_report['arm_totals'][arm]
            self.assertEqual(v['attempts'],6)
            self.assertEqual(v['success'],6)
            self.assertEqual(v['weak_any3'],4)
            self.assertEqual(v['weak_all3'],3)
            self.assertEqual(v['strict_literal'],0)
        self.assertFalse(self.reader_report['whole_reader_task_semantic_success_independently_verified'])
        self.assertFalse(self.reader_report['graph_relation_truth_verified'])
        self.assertFalse(self.reader_report['official_hf_operator_parity_verified'])
        self.assertFalse(self.reader_report['production_accepted'])

    def test_original_e3_plan_does_not_contain_publisher_gold(self):
        self.assertFalse(self.plan['publisher_gold_used_in_plan'])
        self.assertNotIn('adversarial_answer',json.dumps(self.plan))
        self.assertNotIn('publisher_support',json.dumps(self.plan))
        self.assertEqual(len(self.plan['cases']),6)
        self.assertEqual(self.plan['eligible_edge_lesion_changes'],{'conv-49':9,'conv-50':6})

    def test_missing_or_swapped_one_reader_treatment_rejected(self):
        tokenizer=r.ArchivedByteLevelBPE(self.root/'reader', expected_tokenizer_sha256=r.TOKENIZER_SHA)
        bad=copy.deepcopy(self.plan)
        bad['cases'][0]['requests'].pop('temporal_fixed')
        with self.assertRaisesRegex(ValueError,'missing graph ablation arm'):
            r.validate_plan(bad,tokenizer)

    def test_publisher_gold_swapped_with_fake_case_rejected(self):
        bad=copy.deepcopy(self.heldout)
        bad['public_sha256']='f'*64
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'heldout.json';e.put_new(p,bad)
            with self.assertRaisesRegex(ValueError,'gold/QA source mismatch'):
                r.postseal_score(self.plan,self.root/'reader',self.root/'original-e3-reader-24',
                    self.root/'original/locomo.json',e.CORPUS_SHA,p,e.sha_bytes(p.read_bytes()),
                    Path(d)/'result.json')

    def test_fake_independent_future_or_accepted_production_denied(self):
        tokenizer=r.ArchivedByteLevelBPE(self.root/'reader', expected_tokenizer_sha256=r.TOKENIZER_SHA)
        for k,value in (('independent_future_windows',2),('production_accepted',True),
                        ('official_hf_parity_verified',True)):
            bad=copy.deepcopy(self.plan);bad[k]=value
            with self.assertRaises(ValueError):r.validate_plan(bad,tokenizer)

    def test_tampered_durable_original_reader_answer_denied(self):
        folder=self.root/'original-e3-reader-24'
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)
            (path/'starts.jsonl').write_bytes((folder/'starts.jsonl').read_bytes())
            rows=r.load_lines(folder/'raw_answers.jsonl')
            rows[0]['raw_answer']+=' forged model output'
            # Even if an untrusted producer recomputes the answer SHA and seal,
            # original model token IDs must decode to the unchanged model text.
            rows[0]['raw_answer_sha256']=e.sha_bytes(rows[0]['raw_answer'].encode())
            (path/'raw_answers.jsonl').write_bytes(b''.join(e.canonical(v) for v in rows))
            seal=json.loads((folder/'seal.json').read_bytes())
            seal['answer_file_sha256']=e.sha_bytes((path/'raw_answers.jsonl').read_bytes())
            (path/'seal.json').write_bytes(e.canonical(seal))
            with self.assertRaisesRegex(ValueError,'original raw Reader text/token tampering'):
                r.recount(self.plan,self.root/'reader',path)

    def test_dropped_started_or_failed_reader_call_denied(self):
        folder=self.root/'original-e3-reader-24'
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)
            starts=r.load_lines(folder/'starts.jsonl')
            (path/'starts.jsonl').write_bytes(b''.join(e.canonical(v) for v in starts[:-1]))
            (path/'raw_answers.jsonl').write_bytes((folder/'raw_answers.jsonl').read_bytes())
            seal=json.loads((folder/'seal.json').read_bytes())
            seal['start_file_sha256']=e.sha_bytes((path/'starts.jsonl').read_bytes())
            (path/'seal.json').write_bytes(e.canonical(seal))
            with self.assertRaisesRegex(ValueError,'missing original Reader answers'):
                r.recount(self.plan,self.root/'reader',path)

    def test_tampered_publisher_corpus_requires_exact_real_SHA(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'original.json'
            p.write_bytes((self.root/'original/locomo.json').read_bytes()+b'\n')
            with self.assertRaisesRegex(ValueError,'unregistered original LoCoMo'):
                r.postseal_score(self.plan,self.root/'reader',self.root/'original-e3-reader-24',
                    p,e.CORPUS_SHA,self.root/'original-withheld.json',
                    e.sha_bytes((self.root/'original-withheld.json').read_bytes()),
                    Path(d)/'result.json')

    def test_false_null_graph_lesion_is_not_physical_intervention(self):
        bad=copy.deepcopy(self.plan)
        bad['cases'][0]['requests']['temporal_edge_lesion']=copy.deepcopy(
            bad['cases'][0]['requests']['temporal_learned'])
        tok=r.ArchivedByteLevelBPE(self.root/'reader', expected_tokenizer_sha256=r.TOKENIZER_SHA)
        with self.assertRaisesRegex(ValueError,'not a real graph intervention'):
            r.validate_plan(bad,tok)

    def test_train_only_owners_are_not_heldout_family_labeled(self):
        require_train={f for f,v in e.SPLITS.items() if v=='train'}
        self.assertEqual(set(self.weights['training_families']),require_train)
        self.assertFalse(set(self.weights['training_families'])&set(e.HELDOUT))


if __name__=='__main__':unittest.main()
