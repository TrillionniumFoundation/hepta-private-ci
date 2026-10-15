"""Explicit synthetic negative-contract mutations only."""
import copy
import unittest
from v13_reader_public_gate import gate,CORPUS

class PublicReaderDenial(unittest.TestCase):
    def setUp(self):
        self.pub=dict(schema='hepta.stem.v13.original-lexical-reader-diagnostic.v1.sanitized-physical-diagnostic.v1',
            original_corpus_sha256=CORPUS,source_plan_sha256='a'*64,original_answer_file_sha256='b'*64,
            source_first_original_cases=16,genuine_original_reader_requests=32,independent_retrospective_source_roots=4,
            original_reader_forward_calls=772,original_answers_changed_between_routes=5,
            selected_conditioned_on_evidence_membership_difference=True,
            per_arm={'bm25':{'any_weak_support':5,'missing_or_ambiguous_weak_annotation':0,'input_tokens':2600,'output_tokens':370},
                     'phrase_char':{'any_weak_support':5,'missing_or_ambiguous_weak_annotation':0,'input_tokens':2629,'output_tokens':372}},
            official_HF_parity=False,original_task_semantic_correctness=None,new_calendar_future_windows=0,
            model_learning_utility_verified=False,equal_end_to_end_compute=False,production_authorized=False,stem_winner_verified=False)
        self.ind=dict(schema='hepta.stem.v13.original-reader-independent-private-audit.v1',source_plan_sha256='a'*64,
            first_original_reader_sha256='b'*64,status='PRIVATE_ORIGINAL_RECOUNT_NO_GO',historical_family_roots=4,
            original_questions=16,original_calls_per_run=32,original_reader_answers_reproduced=32,original_changed_answers=5,
            publisher_weak_hits_bm25=5,publisher_weak_hits_primary=5,new_future_windows=0,semantic_correctness=None,
            original_reader_HF_parity=False,second_source_bounded=True,production_authorized=False,stem_winner_verified=False)
    def test_valid_no_go(self):self.assertEqual(gate(self.pub,self.ind)['observed_weak_hit_delta'],0)
    def mut_pub(self,key,value):
        self.pub[key]=value
        with self.assertRaises(ValueError):gate(self.pub,self.ind)
    def test_fabricated_hf_parity(self):self.mut_pub('official_HF_parity',True)
    def test_fabricated_semantics(self):self.mut_pub('original_task_semantic_correctness',.9)
    def test_new_future_claim(self):self.mut_pub('new_calendar_future_windows',3)
    def test_false_equal_compute(self):self.mut_pub('equal_end_to_end_compute',True)
    def test_promotion(self):self.mut_pub('production_authorized',True)
    def test_fake_stem_winner(self):self.mut_pub('stem_winner_verified',True)
    def test_wrong_model_calls(self):self.mut_pub('original_reader_forward_calls',777)
    def test_lost_request(self):self.mut_pub('genuine_original_reader_requests',31)
    def test_correlated_as_independent_cases(self):self.mut_pub('independent_retrospective_source_roots',16)
    def test_hidden_selection(self):self.mut_pub('selected_conditioned_on_evidence_membership_difference',False)
    def test_wrong_weak_hits(self):
        self.pub['per_arm']['phrase_char']['any_weak_support']=6
        with self.assertRaises(ValueError):gate(self.pub,self.ind)
    def test_changed_reader_prompt_tokens(self):
        self.pub['per_arm']['phrase_char']['input_tokens']+=1
        with self.assertRaises(ValueError):gate(self.pub,self.ind)
    def test_wrong_original_source_sha(self):self.mut_pub('original_corpus_sha256','0'*64)
    def test_independent_replay_fabricated(self):
        self.ind['original_reader_answers_reproduced']=31
        with self.assertRaises(ValueError):gate(self.pub,self.ind)
    def test_independent_label_claim(self):
        self.ind['semantic_correctness']=True
        with self.assertRaises(ValueError):gate(self.pub,self.ind)
    def test_independent_plan_digest(self):
        self.ind['source_plan_sha256']='0'*64
        with self.assertRaises(ValueError):gate(self.pub,self.ind)

if __name__=='__main__':unittest.main()
