"""E22 no-label-only original archive contracts: do not open human scores."""
from __future__ import annotations
import copy
from pathlib import Path
import os
from unittest import TestCase
from unittest.mock import patch

import e22_e16_question_gate as gate


def originals():
    source = os.environ.get('HEPTA_E22_ARCHIVE')
    e15 = [os.environ.get(f'HEPTA_E22_E15_FOLD_{i}') for i in range(4)]
    e16 = [os.environ.get(f'HEPTA_E22_E16_FOLD_{i}') for i in range(4)]
    if not source or any(not x for x in e15 + e16):
        raise ValueError('E22 requires nine actual immutable original PRELABEL ZIPs')
    if any(not Path(x).is_file() for x in [source] + e15 + e16):
        raise ValueError('real original ZIP missing: no synthetic source fallback')
    return source, e15, e16


class OriginalBlindE22(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source,cls.e15,cls.e16 = originals()
        cls.report = gate.blind_e22(cls.source,cls.e15,cls.e16)

    def test_01_original_full_source_identity(self):
        d=self.report
        self.assertEqual((d['source_passages'],d['questions'],d['candidates']),(4,8,33))
        self.assertEqual(len({r['task_id'] for r in d['rows']}),33)
        self.assertEqual(len({(r['source_group'],r['question_slot']) for r in d['rows']}),8)

    def test_02_original_eight_distinct_control_and_learner_arms(self):
        self.assertEqual(len(gate.ALL),8)
        self.assertTrue(all(set(r['probs']) == set(gate.ALL) for r in self.report['rows']))

    def test_03_no_original_held_labels_or_promotion(self):
        self.assertEqual(self.report['authority'],'DENY_ALL')
        self.assertFalse(self.report['human_labels_opened'])
        self.assertFalse(self.report['model_selected'])
        self.assertFalse(self.report['system2_fbsde_permitted'])
        self.assertFalse(self.report['production_accepted'])
        self.assertEqual(self.report['new_pretrained_forwards'],0)
        self.assertFalse(any('label' in r or 'truth' in r for r in self.report['rows']))

    def test_04_exact_trainable_count_and_really_metered_heads(self):
        met=self.report['e16_observed_student_CPU_ns']
        self.assertEqual(len(met),8)
        self.assertEqual(sum(m['parameter_count'] for m in met),40)
        self.assertTrue(all(m['steps']==48 and m['train_cpu_ns']>0 and m['held_cpu_ns']>0 for m in met))
        self.assertTrue(self.report['original_training_and_inference_costs_not_complete'])

    def test_05_original_source_models_not_backfilled(self):
        self.assertEqual(gate.SOURCE_SHA,'1a9b485b6b1ee28c952934069b2cd4d765a17742655f3f3cb3339d3ca672ad17')
        self.assertEqual(gate.E16_HEAD,'09d0528d95ca2cab997d4e17f499b098dc1fdb29')

    def test_06_duplicate_or_missing_original_fold_fails_closed(self):
        with self.assertRaises(ValueError):gate.blind_e22(self.source,self.e15,self.e16[:3])
        bad=self.e16[:];bad[2]=bad[0]
        with self.assertRaises(ValueError):gate.blind_e22(self.source,self.e15,bad)

    def test_07_untrusted_source_requires_exact_ZIP(self):
        with self.assertRaises((ValueError,FileNotFoundError)):gate.blind_e22(self.source+'-not-a-real-archive',self.e15,self.e16)
        with self.assertRaises(ValueError):gate.blind_e22(self.source,self.e15,self.e16[:1]+self.e16[2:]+self.e16[:1])

    def test_08_blind_opener_never_reads_score_or_label_member(self):
        read=[];original=gate._zip
        def guard(filename, sha, names):
            read.extend(names)
            self.assertFalse(any('scores' in name or 'owner-label' in name or 'human' in name for name in names))
            return original(filename,sha,names)
        with patch.object(gate,'_zip',guard):
            b=gate.blind_e22(self.source,self.e15,self.e16)
        self.assertEqual(len(b['rows']),33)
        self.assertTrue(read)

    def test_09_question_invariant_noquery_source(self):
        per={}
        for r in self.report['rows']:
            per.setdefault((r['source_group'],r['question_slot']),set()).add(r['probs']['no_query'])
        self.assertEqual(len(per),8)
        self.assertTrue(all(len(s)==1 for s in per.values()))

    def test_10_real_e16_models_make_different_probabilities(self):
        self.assertTrue(any(abs(r['probs']['centered_raw_5']-r['probs']['centered_scaled_5'])>1e-6
                            for r in self.report['rows']))

    def test_11_repeated_source_validation_deterministic_except_cpu(self):
        x=gate.blind_e22(self.source,self.e15,self.e16)
        self.assertEqual(x,self.report)

    def test_12_no_fabricated_future_or_authority_field(self):
        self.assertNotIn('prospective_gain',self.report)
        self.assertNotIn('total_online_cost_gain',self.report)
        self.assertNotIn('human_labels',self.report)
        self.assertEqual(self.report['schema'],gate.SCHEMA)
