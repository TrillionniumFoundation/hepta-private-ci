"""Adversarial source-only negative gates; no original pretrained execution here."""
import copy
import json
from pathlib import Path
import unittest
from v19_public_no_go import audit
HERE=Path(__file__).parent

class SourceOnlyNoGo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original=json.loads((HERE/'STEM_V19_ORIGINAL_CONTEXT_WINDOWS_20261016.json').read_text())
    def setUp(self):self.x=copy.deepcopy(self.original)
    def checkdeny(self,fn):
        fn(self.x)
        with self.assertRaises(ValueError):audit(self.x)
    def test_real_historical_aggregate_denied_for_promotion(self):
        out=audit(self.x)
        self.assertFalse(out['production_authorized']);self.assertIsNone(out['independent_human_correctness'])
    def test_cannot_forge_production(self):self.checkdeny(lambda x:x.update(production_authorized=True))
    def test_cannot_forge_cell_gain(self):self.checkdeny(lambda x:x.update(cell_learning_benefit_verified=True))
    def test_cannot_forge_reader_reference(self):self.checkdeny(lambda x:x.update(reference_reader_physically_executed=True))
    def test_cannot_forge_human_sufficiency(self):self.checkdeny(lambda x:x.update(independently_human_reviewed_source_sufficiency=True))
    def test_cannot_forge_future_windows(self):self.checkdeny(lambda x:x.update(new_source_independent_calendar_windows=2))
    def test_cannot_forge_semantic_accuracy(self):self.checkdeny(lambda x:x.update(human_semantic_task_correctness=0.9))
    def test_cannot_swap_weights(self):self.checkdeny(lambda x:x.update(original_pretrained_weights_sha256='0'*64))
    def test_cannot_relabel_unknown_answers(self):self.checkdeny(lambda x:x.update(original_publisher_answer_unknown=0))
    def test_cannot_claim_extra_original_calls(self):self.checkdeny(lambda x:x.update(new_original_forwards_each=999))
    def test_reject_extra_question(self):self.checkdeny(lambda x:x.update(historical_questions=33))
    def test_reject_fake_equal_model_budget(self):self.checkdeny(lambda x:x.update(matched_full_lifecycle_compute=True))
    def test_reject_fake_long_context(self):self.checkdeny(lambda x:x['per_arm_literal_answer_cohort']['window_plus_2'].update(answer_in_source=16))
    def test_reject_swapped_labels(self):self.checkdeny(lambda x:x['per_arm_literal_answer_cohort']['window_plus_1'].update(answer_in_output=5))
    def test_reject_forged_same_heading(self):self.checkdeny(lambda x:x.update(baseline_and_candidate_same_evidence_heading=False))
    def test_reject_forged_paired_gain(self):self.checkdeny(lambda x:x['paired_literal_contrasts']['window_plus_2_vs_single_sentence'].update(gain=16))
    def test_reject_nonliteral_source_gain(self):self.checkdeny(lambda x:x['per_arm_nonliteral_answer_cohort']['window_plus_1'].update(answer_in_source=1))
    def test_reject_fabricated_rss_as_cost(self):self.checkdeny(lambda x:x.update(first_cpu_seconds=0))
    def test_reject_dropped_original_family(self):self.checkdeny(lambda x:x['per_family_source_counts'].pop('conv-48'))
if __name__=='__main__':unittest.main()
