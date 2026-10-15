"""Hermetic contract against exact original sanitized 80-call negative receipt."""
import copy
import json
import unittest
from pathlib import Path

from amcn_reader_sufficiency_gate import verdict

RECEIPT=json.loads(Path(__file__).with_name('ORIGINAL_READER_SUFFICIENCY_20261015.json').read_text())

class PhysicalNegativeGateContract(unittest.TestCase):
    def test_original_eighty_reader_calls_cannot_promote(self):
        v=verdict(RECEIPT)
        self.assertEqual(v['original_physical_reader_attempts_recounted_from_author_receipts'],80)
        self.assertEqual(v['verbatim_8_oracle_answer_substring_proxy'],4)
        self.assertFalse(v['production_accepted'])
        self.assertFalse(v['human_sufficient_evidence_verified'])

    def bad(self,mutate,reason=None):
        a=copy.deepcopy(RECEIPT);mutate(a)
        with self.assertRaisesRegex(ValueError,reason or '.*'):
            verdict(a)

    def test_fabricated_human_attestation_denied(self):
        self.bad(lambda a:a.update(independent_human_verified_sufficient_evidence=True))

    def test_fabricated_sufficiency_denied(self):
        self.bad(lambda a:a.update(reader_sufficiency_full_task_proven=True))

    def test_fabricated_HF_parity_denied(self):
        self.bad(lambda a:a.update(original_reader_HF_parity_verified=True))

    def test_fabricated_future_denied(self):
        self.bad(lambda a:a.update(true_future_calendar_windows=2))

    def test_fabricated_production_admission_denied(self):
        self.bad(lambda a:a.update(production_accepted=True))

    def test_missing_failed_call_denied(self):
        self.bad(lambda a:a['cohorts']['annotation_only_12'].update(actual_completed_reader_calls=47))

    def test_missing_family_denied(self):
        self.bad(lambda a:a['cohorts']['verbatim_stress_8']['family_root_counts'].pop('conv-50'))

    def test_publisher_answer_opened_for_selection_cannot_be_rebranded_blind(self):
        self.bad(lambda a:a['cohorts']['verbatim_stress_8'].update(case_selection_uses_publisher_gold_answer=False))

    def test_faked_oracle_sufficiency_denied(self):
        self.bad(lambda a:a['cohorts']['annotation_only_12'].update(publisher_witness_human_verified=True))

    def test_malformed_delivered_answer_counts_denied(self):
        self.bad(lambda a:a['cohorts']['verbatim_stress_8']['arm_totals']['publisher_annotated_witness'].update(strict_literal=4))

    def test_misreported_string_substring_denied(self):
        self.bad(lambda a:a['cohorts']['verbatim_stress_8']['arm_totals']['publisher_annotated_witness'].update(publisher_answer_substring_proxy=8))

    def test_misreported_output_budget_denied(self):
        self.bad(lambda a:a['cohorts']['annotation_only_12']['arm_totals']['original_bm25_top3'].update(output_tokens=900))

    def test_misreported_equal_compute_denied(self):
        self.bad(lambda a:a.update(actual_total_Reader_compute_equal=True))

    def test_fake_independent_semantic_judgment_denied(self):
        self.bad(lambda a:a.update(independent_semantic_judgment={'some_score':1.0}))

    def test_missing_raw_output_receipt_denied(self):
        self.bad(lambda a:a['cohorts']['annotation_only_12'].pop('original_raw_answers_sha256'))

if __name__=='__main__':unittest.main()
