import copy
import json
import unittest
from pathlib import Path
from stem_v10_family_audit import audit,digest

DATA=Path(__file__).with_name('STEM_V9_POSTSEAL_WEAK_SCORES_20261015.json').read_bytes()

class AuditTests(unittest.TestCase):
    def setUp(self):self.v=json.loads(DATA)
    def accept(self):return audit(self.v,original_sha=digest(DATA))
    def test_original(self):
        d=self.accept();self.assertEqual(d['weak_hit3_counts']['bm25_full'],372)
        self.assertFalse(d['learned_head_superiority_verified'])
    def test_missing_arm(self):
        del self.v['per_arm_source_root_aggregates']['seed41/frozen']
        with self.assertRaises(ValueError):self.accept()
    def test_missing_root(self):
        del self.v['per_arm_source_root_aggregates']['bm25_full']['conv-47']
        with self.assertRaises(ValueError):self.accept()
    def test_changed_count(self):
        self.v['per_arm_source_root_aggregates']['bm25_full']['conv-47']['any_support_top3']-=1
        with self.assertRaises(ValueError):self.accept()
    def test_bool_as_count(self):
        self.v['per_arm_source_root_aggregates']['bm25_full']['conv-47']['any_support_top3']=True
        with self.assertRaises(ValueError):self.accept()
    def test_fake_independence(self):
        self.v['heldout_source_family_count']=829
        with self.assertRaises(ValueError):self.accept()
    def test_fake_future(self):
        self.v['independent_calendar_future_windows']=2
        with self.assertRaises(ValueError):self.accept()
    def test_fake_acceptance(self):
        self.v['production_authorized']=True
        with self.assertRaises(ValueError):self.accept()
    def test_fake_task_result(self):
        self.v['independent_human_task_success']=0.8
        with self.assertRaises(ValueError):self.accept()
    def test_malformed_root(self):
        self.v['per_arm_source_root_aggregates']['bm25_full']['conv-47']['unknown_annotation']=-1
        with self.assertRaises(ValueError):self.accept()
    def test_wrong_schema(self):
        self.v['schema']='v10'
        with self.assertRaises(ValueError):self.accept()
    def test_wrong_pin(self):
        with self.assertRaises(ValueError):audit(self.v,original_sha='x')
    def test_other_sixty_four_digit_pin_denied(self):
        with self.assertRaises(ValueError):audit(self.v,original_sha='0'*64)
    def test_bad_prediction_lineage(self):
        self.v['original_predictions_sha256']='0'*64
        with self.assertRaises(ValueError):self.accept()
    def test_fake_full_task_reader(self):
        self.v['reader_full_task_answer_calls']=24
        with self.assertRaises(ValueError):self.accept()
    def test_fake_equal_total_compute(self):
        self.v['equal_total_lifecycle_compute']=True
        with self.assertRaises(ValueError):self.accept()

if __name__=='__main__':unittest.main()
