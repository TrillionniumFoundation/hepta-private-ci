"""Fast source-only integrity tests for independent real E3 retrospective NO-GO."""
import copy,json,unittest
from pathlib import Path
from amcn_original_temporal_e3_gate import negative_original_verdict

SOURCE=Path(__file__).with_name('ORIGINAL_TEMPORAL_E3_20261015.json')

class IndependentOriginalE3Denial(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.original=json.loads(SOURCE.read_bytes())

    def check_change(self,mutate):
        data=copy.deepcopy(self.original)
        mutate(data)
        with self.assertRaises(ValueError):negative_original_verdict(data)

    def test_true_original_400_questions_remain_graph_no_go(self):
        r=negative_original_verdict(self.original)
        self.assertEqual(r['original_retrospective_questions'],400)
        self.assertEqual(r['learned_graph_minus_fixed_weak_hit3_proxy'],-6)
        self.assertIsNone(r['reader_independent_semantic_success'])
        self.assertFalse(r['automatic_cell_fission_fusion_eligible'])

    def test_false_future_window_denied(self):
        self.check_change(lambda x:x.update(real_future_calendar_windows=2))

    def test_faked_causal_relation_authority_denied(self):
        self.check_change(lambda x:x.update(source_relationships_causal_truth_confirmed=True))

    def test_spurious_meta_network_superiority_denied(self):
        self.check_change(lambda x:x.update(graph_learning_task_superiority_proven=True))

    def test_changed_reader_count_denied(self):
        self.check_change(lambda x:x.update(original_reader_attempts_sealed=20))

    def test_changed_graph_zero_train_weights_denied(self):
        self.check_change(lambda x:x['train_relation_scientific_details']['weights'].__setitem__('associative',0.2))

    def test_missing_case_denominator_denied(self):
        self.check_change(lambda x:x['within_experiment_retrieval_weak_support']['temporal_learned'].__setitem__('questions',399))

    def test_changed_weak_top3_proxy_denied(self):
        self.check_change(lambda x:x['within_experiment_retrieval_weak_support']['temporal_learned'].__setitem__('hit3',200))

    def test_faked_independent_semantic_answer_denied(self):
        self.check_change(lambda x:x.update(full_reader_task_semantic_success_independently_verified=True))

    def test_faked_cost_parity_denied(self):
        self.check_change(lambda x:x.update(strong_hybrid_rag_equal_total_compute_compared=True))

    def test_faked_physical_cpu_owner_denied(self):
        self.check_change(lambda x:x.update(repeated_physical_coefficients_bitwise_equal=False))

    def test_faked_reader_token_count_denied(self):
        self.check_change(lambda x:x['reader_diagnostic_weak_and_literal']['temporal_learned'].__setitem__('input_tokens',1139))

    def test_omit_original_graph_lesion_denied(self):
        self.check_change(lambda x:x['within_experiment_retrieval_weak_support'].pop('temporal_edge_lesion'))

    def test_false_auto_promotion_denied(self):
        self.check_change(lambda x:x.update(automatic_cell_fission_and_model_promotion_authorized=True))

    def test_unknown_source_pin_denied(self):
        self.check_change(lambda x:x.update(source_corpus_sha256='f'*64))

if __name__=='__main__':unittest.main()
