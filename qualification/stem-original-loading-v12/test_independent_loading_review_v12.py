"""Independent *synthetic* model-loading status denial tests; no model data."""
from __future__ import annotations
import copy
import sys
import types
from pathlib import Path
import unittest

if 'paired_review_v5' not in sys.modules and not (
        Path(__file__).resolve().parents[1]/'stem-optimal-v5'/'paired_review_v5.py').is_file():
    sys.modules['paired_review_v5']=types.ModuleType('paired_review_v5')
import independent_loading_review_v12 as reviewer


def fixture():
    old={'candidate':'granite47','source_plan_sha256':'a'*64,
         'model_revision':'c'*40,'actual_weight_sha256':'b'*64,
         'initial_head_sha256':'d'*64,'trained_head_sha256':'e'*64}
    report={'schema':reviewer.SCHEMA,'candidate':'granite47','profile':'auto_model',
            'load_status':'complete',
            'source_plan_sha256':'a'*64,'original_model_revision':'c'*40,
            'original_weight_sha256':'b'*64,
            'original_initial_head_sha256':'d'*64,'observed_initial_head_sha256':'d'*64,
            'initial_head_byte_equal':True,'original_trained_head_sha256':'e'*64,
            'observed_trained_head_sha256':'e'*64,'trained_head_byte_equal':True,
            'load_diagnostics':{
                'missing_keys':[], 'missing_key_count':0,'unexpected_key_count':2,
                'mismatched_keys':[],'mismatched_key_count':0,
                'error_messages':[],'error_count':0,'model_base_weights_complete':True,
                'complete_model_resident_parameter_scalars':12345,
                'loader_class':'OriginalModel','base_model_class':'BaseModel'},
            'historical_original_probability_max_abs_drift':{'frozen_init':1e-5,
                'centroid':2e-5,'learned':3e-5},
            'scientifically_fully_reproducible_same_head_and_base':True,
            'original_encoder_sequences_paid':72,'original_encoder_batches_paid':5,
            'selected_case_count':8,
            'model_load_wall_seconds':1.,'actual_encode_wall_seconds':2.,
            'actual_head_train_wall_seconds':3.,'total_elapsed_wall_seconds':8.,
            'total_elapsed_cpu_seconds':5.,'self_reported_peak_rss_bytes':100_000_000,
            'authority':'DENY_ALL','disposition':'HOLD_NO_GO',
            'production_authorized':False,'cell_split_authorized':False,
            'stem_winner_verified':False,'ndu_benefit_verified':False,
            'same_host_full_lifecycle_cost_verified':False,
            'retrospective_test_labels_previously_exposed':True}
    return report,old


class NegativeOriginalLoaderTests(unittest.TestCase):
    def test_accepts_data_but_never_selects_a_winner(self):
        report,old=fixture()
        result=reviewer.audit(report,old)
        self.assertTrue(result['all_original_baseline_replay_checks_pass'])
        self.assertEqual(result['score_status'],'DIAGNOSTIC_ONLY_NOT_FUTURE_OR_STEM_SELECTION')

    def test_loader_failure_is_retained_without_forward_or_head_claims(self):
        report,old=fixture()
        report.update({
            'load_status':'failed',
            'load_failure_type':'NotImplementedError',
            'load_failure_message':'Cannot copy out of meta tensor',
            'observed_initial_head_sha256':'',
            'initial_head_byte_equal':False,
            'observed_trained_head_sha256':'',
            'trained_head_byte_equal':False,
            'original_encoder_sequences_paid':0,
            'original_encoder_batches_paid':0,
            'actual_encode_wall_seconds':0.0,
            'actual_head_train_wall_seconds':0.0,
            'total_elapsed_wall_seconds':1.0,
            'total_elapsed_cpu_seconds':1.0,
            'historical_original_probability_max_abs_drift':{'frozen_init':0.0,
            'centroid':0.0,'learned':0.0},

            'scientifically_fully_reproducible_same_head_and_base':False,
        })
        report['load_diagnostics'].update({
            'error_messages':['NotImplementedError: Cannot copy out of meta tensor'],
            'error_count':1,
            'model_base_weights_complete':False,
            'complete_model_resident_parameter_scalars':0,
            'loader_class':'AutoModelForMaskedLM',
            'base_model_class':'unavailable',
        })
        result=reviewer.audit(report,old)
        self.assertEqual(result['score_status'],'LOADER_FAILURE_RETAINED_NO_GO')
        self.assertFalse(result['all_original_baseline_replay_checks_pass'])

    def test_original_newly_initialized_mmbert_embedding_denied(self):
        report,old=fixture()
        report['load_diagnostics']['missing_keys']=['embeddings.tok_embeddings.weight']
        report['load_diagnostics']['missing_key_count']=1
        report['load_diagnostics']['model_base_weights_complete']=False
        report['scientifically_fully_reproducible_same_head_and_base']=False
        result=reviewer.audit(report,old)
        self.assertFalse(result['complete_pretrained_base_weights'])
        self.assertFalse(result['all_original_baseline_replay_checks_pass'])

    def test_missing_weights_but_forged_qualification_rejected(self):
        report,old=fixture()
        report['load_diagnostics']['missing_keys']=['embeddings.tok_embeddings.weight']
        report['load_diagnostics']['missing_key_count']=1
        with self.assertRaises(ValueError):reviewer.audit(report,old)

    def test_head_digest_mismatch_cannot_claim_exact_replay(self):
        report,old=fixture()
        report['observed_trained_head_sha256']='f'*64
        with self.assertRaises(ValueError):reviewer.audit(report,old)
        report['trained_head_byte_equal']=False
        report['scientifically_fully_reproducible_same_head_and_base']=False
        self.assertFalse(reviewer.audit(report,old)['all_original_baseline_replay_checks_pass'])

    def test_nonfinite_probability_drift_and_fake_costs_refused(self):
        for change in (
            lambda x:x['historical_original_probability_max_abs_drift'].__setitem__('learned',float('nan')),
            lambda x:x.__setitem__('total_elapsed_wall_seconds',0.5),
            lambda x:x.__setitem__('original_encoder_sequences_paid',64),
            lambda x:x.__setitem__('production_authorized',True),
            lambda x:x.__setitem__('same_host_full_lifecycle_cost_verified',True)):
            report,old=fixture();change(report)
            with self.assertRaises(ValueError):reviewer.audit(report,old)

    def test_invalid_model_or_profile_denied(self):
        report,old=fixture();report['profile']='full_mlm'
        with self.assertRaises(ValueError):reviewer.audit(report,old)

if __name__=='__main__':unittest.main()
