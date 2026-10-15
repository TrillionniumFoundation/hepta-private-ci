"""E23 original human-label *receipt* and six-arm hard-class obstruction tests.

Real successful original E14 and both E15 archived score ZIPs are mandatory.
Tests do not access true raw human labels, and are not future efficacy.
"""
from __future__ import annotations
import copy
import hashlib
import os
from pathlib import Path
import tempfile
import unittest

import e23_mixed_question_certificate as c
import e22_answer_discrimination as e22


class CertificateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        required = ('HEPTA_E23_BLIND','HEPTA_E23_E14',
                    'HEPTA_E23_E15_SOURCE','HEPTA_E23_E15_MERGE')
        if any(not os.environ.get(x) for x in required):
            raise ValueError('four genuine original model and human-score archive inputs required; no fixture fallback')
        cls.blind_path = Path(os.environ['HEPTA_E23_BLIND'])
        cls.e14_path = Path(os.environ['HEPTA_E23_E14'])
        cls.e15s_path = Path(os.environ['HEPTA_E23_E15_SOURCE'])
        cls.e15m_path = Path(os.environ['HEPTA_E23_E15_MERGE'])
        cls.blind = e22.load(cls.blind_path)[1]
        cls.e14, cls.e15s, cls.e15m = c.authenticate_receipts(
            cls.e14_path, cls.e15s_path, cls.e15m_path)
        cls.report = c.certify(cls.blind, cls.e14, cls.e15s, cls.e15m)

    def test_real_archive_mixed_question_witness(self):
        self.assertIs(self.e14['all_questions_mixed_original_labels'],True)
        self.assertEqual(self.e15s['original_human_label_mixed_question_count'],8)
        self.assertEqual(self.e15m['original_human_label_mixed_question_count'],8)

    def test_actual_unmodified_hard_class_bounds(self):
        expected={'conditioned':0,'mean_pool_query_fused':0,'no_query':0,
                  'learned_linear_5':0,'learned_gated_3':0,'no_evidence':1}
        self.assertEqual({k:v['current_unmodified_binary_policy_max_complete_questions']
                          for k,v in self.report['arm_upper_bounds'].items()},expected)

    def test_exact_score_invariance_not_equated_to_hard_threshold(self):
        r=self.report['arm_upper_bounds']
        self.assertEqual(r['no_query']['deterministic_reclassifier_using_only_exact_score_max_complete_questions'],0)
        self.assertEqual(r['conditioned']['deterministic_reclassifier_using_only_exact_score_max_complete_questions'],4)
        self.assertEqual(r['mean_pool_query_fused']['deterministic_reclassifier_using_only_exact_score_max_complete_questions'],8)

    def test_all_original_current_policies_have_zero_complete_passage_bound(self):
        for arm,r in self.report['arm_upper_bounds'].items():
            self.assertEqual(r['current_unmodified_binary_policy_max_complete_passages'],0,arm)

    def test_high_noquery_candidate_score_is_not_whole_question(self):
        r=self.report['arm_upper_bounds']['no_query']
        self.assertEqual(r['historical_original_human_candidate_correct'],19)
        self.assertEqual(r['current_unmodified_binary_policy_max_complete_questions'],0)

    def test_two_e15_score_artifacts_agree_with_e14_frozen(self):
        for arm in e22.ALL:
            self.assertEqual(self.e15s['summary'][arm]['correct'],self.e15m['summary'][arm]['correct'])
        for arm in e22.FROZEN:
            self.assertEqual(self.e14['evaluation_arms'][arm]['correct'],self.e15s['summary'][arm]['correct'])

    def test_forged_human_mixed_question_claim_rejected(self):
        edits=((0,'all_questions_mixed_original_labels',False),
               (1,'original_human_label_mixed_question_count',7),
               (2,'original_human_label_mixed_question_count',7))
        for target,key,value in edits:
            copies=copy.deepcopy([self.e14,self.e15s,self.e15m])
            copies[target][key]=value
            with self.subTest(target=target),self.assertRaises(c.CertificateDenied):
                c.certify(self.blind,*copies)

    def test_changed_real_blind_noquery_probability_rejected(self):
        b=copy.deepcopy(self.blind)
        b['rows'][0]['probs']['no_query']=.123456789
        with self.assertRaises(c.CertificateDenied):
            c.certify(b,self.e14,self.e15s,self.e15m)

    def test_tampered_original_score_outer_zip_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            wrong=Path(d)/'wrong.zip'
            wrong.write_bytes(self.e14_path.read_bytes()+b'altered')
            with self.assertRaises(c.CertificateDenied):
                c.authenticate_receipts(wrong,self.e15s_path,self.e15m_path)

    def test_missing_second_independent_E15_score_denied(self):
        with self.assertRaises(c.CertificateDenied):
            c.authenticate_receipts(self.e14_path,self.e15s_path,Path('/missing-e23-merge.zip'))

    def test_no_new_model_or_fabricated_issuer_efficacy(self):
        for key in ('human_label_parquet_reopened_here',
                    'whole_question_original_human_score_recomputed_here',
                    'historical_issuer_and_host_signatures_newly_verified',
                    'external_source_and_future_groups_validated',
                    'new_10t_100t_equivalence_certified',
                    'reader_information_sufficiency_accepted',
                    'full_NDU_system2_admitted','production_accepted'):
            self.assertIs(self.report[key],False)
        self.assertEqual(self.report['authority_posture'],'DENY_ALL')

    def test_create_once_durable_diagnostic(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'new-certificate.json'
            receipt=e22.emit_once(p,self.report)
            self.assertEqual(receipt,hashlib.sha256(p.read_bytes()).hexdigest())
            with self.assertRaises(FileExistsError):
                e22.emit_once(p,self.report)


if __name__=='__main__':
    unittest.main()
