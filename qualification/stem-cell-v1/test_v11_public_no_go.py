import copy
import json
from pathlib import Path
import unittest
from v11_public_no_go import verify
from v11_independent_recount import compare

ORIGINAL=json.loads(Path(__file__).with_name('STEM_V11_ORIGINAL_LEXICAL_RESIDUAL_20261015.json').read_bytes())

class NegativeGates(unittest.TestCase):
    def setUp(self):self.data=copy.deepcopy(ORIGINAL)
    def denies(self):
        with self.assertRaises(ValueError):verify(self.data)
    def test_real_sanitized(self):self.assertEqual(verify(self.data)['independent_family_roots'],4)
    def test_fake_model_win(self):self.data['stem_winner_verified']=True;self.denies()
    def test_fake_future(self):self.data['new_independent_future_calendar_windows']=2;self.denies()
    def test_fake_semantic_reader(self):self.data['independent_semantic_answer_correctness']=0.7;self.denies()
    def test_fake_authorization(self):self.data['production_authorized']=True;self.denies()
    def test_wrong_source(self):self.data['v9_original_prediction_sha256']='0'*64;self.denies()
    def test_fake_compute_parity(self):self.data['equal_full_lifecycle_compute']=True;self.denies()
    def test_fake_retention(self):self.data['v6_three_seed_retention_closed']=True;self.denies()
    def test_wrong_parameter_count(self):self.data['per_seed_trainable_head_parameters']=6914;self.denies()
    def test_wrong_training(self):self.data['total_actual_optimizer_updates']=901;self.denies()
    def test_false_three_separate_families(self):self.data['frozen_original_heldout_groups']=829;self.denies()
    def test_dropped_arm(self):del self.data['weak_hit3_family_paired_diagnostics']['seed41/residual'];self.denies()
    def test_missing_root(self):del self.data['weak_hit3_family_paired_diagnostics']['bm25_full']['conv-50'];self.denies()
    def test_changed_weak_hit(self):self.data['weak_publisher_support_top3_per_arm']['seed53/residual']=500;self.denies()
    def test_changed_gain(self):self.data['weak_hit3_family_paired_diagnostics']['seed47/residual']['conv-47']['gained_vs_bm25']+=1;self.denies()
    def test_bool_as_count(self):self.data['weak_hit3_family_paired_diagnostics']['bm25_full']['conv-47']['hit']=True;self.denies()
    def test_wrong_replay(self):self.data['identical_prediction_sha_in_three_original_repeat_processes']=False;self.denies()
    def test_falsified_all_family_gain(self):self.data['all_heldout_family_nonregression']=True;self.denies()
    def test_synthetic_census_refusal(self):
        with self.assertRaises(ValueError):compare({}, {}, {})

if __name__=='__main__':unittest.main()
