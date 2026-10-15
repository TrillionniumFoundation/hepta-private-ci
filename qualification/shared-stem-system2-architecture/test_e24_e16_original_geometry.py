"""Exact original-E16 archive replay tests, NEVER synthetic substitute archives.

Old public human scored 20/33 performance is not measured here; this tests
source-blind discrimination and original SHA-bound model/case geometry only.
"""
from __future__ import annotations
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

import e24_e16_original_geometry as m

class RealE16OriginalGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        names=('HEPTA_E24_SOURCE',)+tuple('HEPTA_E24_FOLD_'+str(i) for i in range(4))
        if any(not os.environ.get(k) for k in names):
            raise ValueError('five real original ZIP files required; NO mock/fake fallback')
        cls.source=Path(os.environ[names[0]])
        cls.folds=[Path(os.environ[k]) for k in names[1:]]
        cls.result=m.review(cls.source,cls.folds)

    def test_actual_original_prelabel_census_and_scope(self):
        x=self.result
        self.assertEqual((x['original_question_count'],x['original_passages'],x['original_candidates']),(8,4,33))
        self.assertTrue(x['real_original_archive_bytes_reopened'])
        self.assertEqual(x['authority'],'DENY_ALL')
        self.assertFalse(x['production_accepted'])

    def test_real_five_parameter_raw_vs_scaled_hard_information(self):
        a=self.result['arms']
        self.assertEqual(a['centered_raw_5']['constant_hard_questions'],8)
        self.assertEqual(a['centered_scaled_5']['constant_hard_questions'],2)
        self.assertEqual(a['centered_scaled_5']['questions_with_two_predicted_classes'],6)
        self.assertEqual(a['centered_raw_5']['questions_with_two_predicted_classes'],0)
        self.assertEqual(a['centered_raw_5']['exactly_constant_score_questions'],0)
        self.assertEqual(a['centered_scaled_5']['exactly_constant_score_questions'],0)

    def test_actual_original_four_folds_and_paid_cpu(self):
        for arm in m.METHODS:
            r=self.result['arms'][arm]
            self.assertEqual(r['four_original_optimizer_steps'],192)
            self.assertEqual(r['original_trainable_parameters_per_fold'],5)
            self.assertGreater(r['four_original_train_cpu_ns'],0)
            self.assertGreater(r['four_original_held_cpu_ns'],0)

    def test_original_complete_source_groups_and_all_questions(self):
        for arm in m.METHODS:
            q=self.result['arms'][arm]['per_question']
            self.assertEqual(len(q),8)
            self.assertEqual(sum(v['original_candidates'] for v in q),33)
            self.assertEqual(len({v['source_group'] for v in q}),4)

    def test_wrong_original_outer_zip_denied(self):
        with tempfile.TemporaryDirectory() as d:
            changed=Path(d)/'tampered.zip'
            changed.write_bytes(self.folds[2].read_bytes()+b'x')
            bad=self.folds[:];bad[2]=changed
            with self.assertRaises(m.Denied):m.review(self.source,bad)

    def test_reordered_or_missing_real_held_fold_rejected(self):
        with self.assertRaises(m.Denied):m.review(self.source,self.folds[:3])
        bad=self.folds[:];bad[3]=bad[2]
        with self.assertRaises(m.Denied):m.review(self.source,bad)

    def test_fake_original_E22_receipt_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'rehashed-fake.json'
            p.write_text(json.dumps({'schema':m.E22_SCHEMA,'authority':'DENY_ALL',
                                     'human_labels_opened':False,'production_accepted':False,
                                     'source_archive_sha256':m.SOURCE_SHA,
                                     'e16_head':m.E16_HEAD,'rows':[]})+'\n')
            with self.assertRaises(m.Denied):m.review(self.source,self.folds,p)

    def test_structural_result_never_certifies_human_quality_or_ndu(self):
        for key in ('original_human_labels_or_score_zip_opened',
                    'e16_scaled_correct_answer_gain_established_by_this_blind_report',
                    'complete_question_success_established',
                    'source_generalization_or_cost_adjusted_win_certified',
                    'NDU_System2_reader_sufficiency_admitted'):
            self.assertFalse(self.result[key],key)
        self.assertEqual(self.result['new_pretrained_forwards_or_training_steps'],0)

    def test_create_only_output_and_semantic_replay(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'new.json'
            record=m.review(self.source,self.folds)
            with path.open('x') as f:f.write(json.dumps(record,sort_keys=True)+'\n')
            self.assertEqual(json.loads(path.read_text()),record)
            with self.assertRaises(FileExistsError):
                with path.open('x'):pass

    def test_duplicate_and_nonfinite_original_style_json_denied(self):
        for bad in (b'{"a":1,"a":2}',b'{"a":NaN}',b'{"a":Infinity}'):
            with self.assertRaises(m.Denied):m.strict(bad)

if __name__=='__main__':unittest.main()
