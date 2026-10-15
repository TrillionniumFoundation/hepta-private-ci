import copy
import json
from pathlib import Path
import unittest

from amcn_original_type14_receipt_gate import assess

ORIGINAL=Path(__file__).with_name('ORIGINAL_TYPE14_READER_20261015.json')


class Original14ResearchNegativeAuthority(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.record=json.loads(ORIGINAL.read_bytes())

    def test_original_real_model_result_denied_production(self):
        v=assess(self.record)
        self.assertEqual(v['actual_reader_model_calls'],42)
        self.assertFalse(v['automatic_cell_fission_or_promotion_eligible'])

    def test_fake_semantic_success_denied(self):
        r=copy.deepcopy(self.record);r['independent_semantic_entailment_verified']=True
        with self.assertRaises(ValueError):assess(r)

    def test_fake_hf_parity_denied(self):
        r=copy.deepcopy(self.record);r['official_hf_parity_verified']=True
        with self.assertRaises(ValueError):assess(r)

    def test_false_equal_compute_denied(self):
        r=copy.deepcopy(self.record);r['equal_total_cost_including_encoder_and_training']=True
        with self.assertRaises(ValueError):assess(r)

    def test_fake_cell_type_win_denied(self):
        r=copy.deepcopy(self.record);r['type_specialization_whole_task_qualified']=True
        with self.assertRaises(ValueError):assess(r)

    def test_omit_case_denied(self):
        r=copy.deepcopy(self.record);r['per_family']['conv-49']['typed_equal_budget']['questions']-=1
        with self.assertRaises(ValueError):assess(r)

    def test_miscount_answer_cost_denied(self):
        r=copy.deepcopy(self.record);r['arm_totals']['typed_equal_budget']['input_tokens']=3424
        with self.assertRaises(ValueError):assess(r)

    def test_unregistered_failure_claim_denied(self):
        r=copy.deepcopy(self.record);r['original_reader_failed_attempts_preserved']=1
        with self.assertRaises(ValueError):assess(r)

    def test_hide_typed_difference_denied(self):
        r=copy.deepcopy(self.record);r['type_different_raw_text_question_count']=0
        with self.assertRaises(ValueError):assess(r)

    def test_omit_replaced_source_denied(self):
        r=copy.deepcopy(self.record);r['source_replacement_questions']=9
        with self.assertRaises(ValueError):assess(r)

    def test_fake_future_window_denied(self):
        r=copy.deepcopy(self.record);r['independent_future_calendar_windows']=2
        with self.assertRaises(ValueError):assess(r)

    def test_make_original_weak_counts_pretty_denied(self):
        r=copy.deepcopy(self.record);r['arm_totals']['typed_equal_budget']['weak_any_at3']=10
        with self.assertRaises(ValueError):assess(r)

    def test_remove_one_family_denied(self):
        r=copy.deepcopy(self.record);r['per_family'].pop('conv-50')
        with self.assertRaises(ValueError):assess(r)

    def test_paired_positive_flip_forgery_denied(self):
        r=copy.deepcopy(self.record);r['paired_weak_support_flips_vs_bm25']['typed_equal_budget']['new_weak_hit_vs_bm25']=9
        with self.assertRaises(ValueError):assess(r)

if __name__=='__main__':unittest.main()
