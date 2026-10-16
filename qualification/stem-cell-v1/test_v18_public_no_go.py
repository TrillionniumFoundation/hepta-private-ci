"""V18 source-only negative checks never execute original Reader."""
import copy
import json
from pathlib import Path
import unittest
import v18_public_no_go as g

FIX=Path(__file__).with_name('STEM_V18_FACTORIAL_ORIGINAL_NEGATIVE_20261016.json')

class PublicGateContracts(unittest.TestCase):
    def setUp(self):self.x=json.loads(FIX.read_text())
    def bad(self,f):
        f(self.x)
        with self.assertRaises(ValueError):g.check(self.x)
    def test_expected_no_go(self):
        o=g.check(self.x);self.assertFalse(o['pretrained_model_forward_attested_by_this_gate']);self.assertFalse(o['production_authorized'])
    def test_missing_root(self):self.bad(lambda x:x['original_source_root_counts'].pop('conv-48'))
    def test_fake_human_truth(self):self.bad(lambda x:x.update(independent_human_semantic_correctness=True))
    def test_fake_source_sufficiency(self):self.bad(lambda x:x.update(human_verified_sufficient_evidence=True))
    def test_changed_outcome(self):self.bad(lambda x:x['original_publisher_answer_substring_proxy_by_cohort']['literal_in_annotated_source']['focused_full_heading'].update(substring=6))
    def test_weak_proxy_promoted(self):self.bad(lambda x:x.update(improved_stem_selected=True))
    def test_forged_reference(self):self.bad(lambda x:x.update(stronger_reference_reader_physically_executed=True))
    def test_forged_forward(self):self.bad(lambda x:x.update(new_original_model_forwards_per_run=0))
    def test_changed_cost(self):self.bad(lambda x:x['factorial_arm_logical_token_counts']['focused_full_heading'].update(input_tokens=123))
    def test_extra_raw_text(self):self.bad(lambda x:x.update(raw_answers='private'))
    def test_false_independent_windows(self):self.bad(lambda x:x.update(independent_future_calendar_windows=3))
    def test_equal_compute_false(self):self.bad(lambda x:x.update(equal_total_lifecycle_model_compute_verified=True))
    def test_int_bool_confusion(self):self.bad(lambda x:x.update(independent_human_reviews_received=False))
    def test_swapped_title_intervention(self):self.bad(lambda x:x['paired_factorial_source_contrasts']['literal_in_annotated_source'].update(heading_effect_full_body_loss=4))
    def test_false_reuse_count(self):self.bad(lambda x:x.update(identical_previous_request_ids_reused=0))
    def test_nonnumeric_cost(self):self.bad(lambda x:x.update(first_process_cpu_seconds='fast'))
    def test_source_sha_missing(self):self.bad(lambda x:x.update(v18_plan_sha256='ab'))

if __name__=='__main__':unittest.main()
