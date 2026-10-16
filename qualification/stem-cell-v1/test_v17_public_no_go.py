"""V17 sanitized source-only negative gate fixtures; NOT pretrained tests."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import unittest
import v17_public_no_go as g

BASE=Path(__file__).resolve().parent/'STEM_V17_ORIGINAL_READER_FOCUS_NEGATIVE_20261016.json'

class V17PublicNegative(unittest.TestCase):
    def setUp(self):self.x=json.loads(BASE.read_text())
    def denies(self,mutation):
        mutation(self.x)
        with self.assertRaises(ValueError):g.validate(self.x)
    def test_valid_original_negative(self):
        r=g.validate(self.x)
        self.assertFalse(r['reader_qualified']);self.assertFalse(r['production_authorized'])
    def test_missing_cases(self):self.denies(lambda x:x.update(selected_retrospective_original_questions=31))
    def test_fake_forward(self):self.denies(lambda x:x.update(genuine_original_model_forwards=1501))
    def test_replay_fake(self):self.denies(lambda x:x.update(double_replay_exact_raw_token_answers=False))
    def test_v6_false_repair(self):self.denies(lambda x:x.update(v6_three_seed_retention_repaired=True))
    def test_reference_fake(self):self.denies(lambda x:x.update(stronger_reference_reader_original_forwards=32))
    def test_semantic_spoof(self):self.denies(lambda x:x.update(semantic_correctness_independently_judged=0.7))
    def test_human_source_spoof(self):self.denies(lambda x:x.update(human_verified_sufficient_evidence=True))
    def test_hf_parity_spoof(self):self.denies(lambda x:x.update(huggingface_operator_tokenizer_parity=True))
    def test_production_spoof(self):self.denies(lambda x:x.update(production_authorized=True))
    def test_new_future_window_spoof(self):self.denies(lambda x:x.update(new_future_calendar_windows=1))
    def test_answer_substring_not_accuracy(self):self.denies(lambda x:x.update(publisher_answer_substring_is_not_semantic_accuracy=False))
    def test_unknown_answers_must_remain_separate(self):
        self.denies(lambda x:x['per_cohort_arm_weak_string_proxy']['not_literal_in_annotated_source']['formatted_full'].update(publisher_answer_unknown=0))
    def test_gain_loss_cannot_swap(self):
        self.denies(lambda x:x['paired_weak_string_proxy']['literal_in_annotated_source'].update(focus_only_loss=0))
    def test_root_not_independent_questions(self):
        self.denies(lambda x:x['per_original_source_root_weak_string_proxy'].pop('conv-48'))
    def test_cpu_cost_unmeasured(self):self.denies(lambda x:x.update(first_physical_process_cpu_seconds=None))
    def test_head_swap(self):self.denies(lambda x:x.update(original_reader_weights_sha256='0'*64))
    def test_old_future_claims(self):self.denies(lambda x:x.update(cell_learning_utility_verified=True))
    def test_training_not_introduced(self):self.denies(lambda x:x.update(focus_selection_used_publisher_answers=True))
    def test_added_publisher_gold(self):self.denies(lambda x:x.update(publisher_answer_text='leak'))
    def test_source_row_gain_contradiction(self):
        self.denies(lambda x:x['per_original_source_root_weak_string_proxy']['conv-47']['formatted_full'].update(answer_substring=8))
    def test_input_token_identity(self):self.denies(lambda x:x['per_arm_tokens']['formatted_focused'].update(input=5679))
    def test_source_changed_must_not_be_32(self):self.denies(lambda x:x.update(source_content_actually_shrunk_cases=32))

if __name__=='__main__':unittest.main()
