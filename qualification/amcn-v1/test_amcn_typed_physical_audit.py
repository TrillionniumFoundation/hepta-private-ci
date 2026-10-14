"""Negative-control receipts for pinned original MiniLM material auditor."""
from copy import deepcopy
import unittest

from amcn_core import Refused, digest
from amcn_typed_physical_audit import (
    audit_receipts, ARCHIVE_SHA, LOCOMO_SHA, MODEL_SHA, SOURCE_PLAN_SHA,
    ARMS, SPLITS, TYPES,
)


def fixture():
    preds = [{'row_id': f'case-{j}', 'probabilities': {'typed_equal_budget': 0.2}}
             for j in range(704)]
    pred_digest = digest(preds)
    feature = {
        'schema': 'hepta.amcn.custom-minilm-real-weights-forward.nonqualifying.v1',
        'source_original_zip_sha256': ARCHIVE_SHA,
        'source_original_locomo_sha256': LOCOMO_SHA,
        'original_source_first_sha256': SOURCE_PLAN_SHA,
        'model_safetensors_sha256': MODEL_SHA,
        'features_shape': [1472, 384],
        'fp32_tensor_bytes': 1472 * 384 * 4,
        'original_model_forward_calls': 92,
        'tensor_file_sha256': digest('tensor'),
        'hf_tokenizer_parity_verified': False,
        'hf_bert_operator_parity_verified': False,
        'train_labels_opened_during_encoding': False,
        'future_labels_opened_during_encoding': False,
    }
    seal = {
        'schema': 'hepta.amcn.original-minilm-manual-forward-typed.head-train.shadow.v1',
        'original_locomo_sha256': LOCOMO_SHA,
        'original_source_first_sha256': SOURCE_PLAN_SHA,
        'model_safetensors_sha256': MODEL_SHA,
        'input_feature_safetensors_sha256': digest('tensor'),
        'actual_pretrained_weight_forward_performed': True,
        'training_sampling': 'balanced_binary',
        'actual_optimizer_steps_per_head': 48,
        'training_parameters_paired': 9272,
        'train_only_original_publisher_weak_support': True,
        'hf_tokenizer_parity_verified': False,
        'hf_bert_operator_parity_verified': False,
        'real_pretrained_source_claim_qualified': False,
        'independent_future_calendar_windows': False,
        'production_accepted': False,
        'predictions': preds,
        'original_prediction_digest': pred_digest,
        'physical_reloaded_prediction_check': {
            'verified_predictions': 704, 'no_label_scores_opened': True,
            'original_predictions_sha256': pred_digest},
    }
    top1_lex = {'select': 4, 'future_a': 2, 'future_b': 3, 'retention': 5}
    top1_typed = {'select': 2, 'future_a': 0, 'future_b': 1, 'retention': 1}
    totals = []
    for split, n in [('select', 8), ('future_a', 4), ('future_b', 4), ('retention', 6)]:
        for i, kind in enumerate(TYPES):
            for arm in ARMS:
                hits = 0
                if i == 0 and arm == 'lexical_top1':
                    hits = top1_lex[split]
                if i == 0 and arm == 'typed_equal_budget':
                    hits = top1_typed[split]
                totals.append({'split': split, 'memory_type': kind, 'arm': arm,
                               'questions': n, 'hit1': hits, 'hitk': n,
                               'no_support_shortlist': 0, 'mrr_at_k': 0.0})
    q = {'production_accepted': False, 'metrics': {
        'profile': 'hepta.amcn.typed-question-recall.shadow.v1',
        'original_predictions_sha256': pred_digest,
        'complete_question_count': 44, 'complete_candidate_count': 704,
        'zero_support_or_zero_hit_questions': 15,
        'future_family_pairs': 2, 'family_wins': {'win':0, 'loss':1, 'tie':1},
        'independent_future_calendar_windows': 0,
        'pretrained_feature_origin_independently_authenticated': False,
        'physical_head_bank_independently_replayed': False,
        'original_reader_answers': None,
        'strong_hybrid_rag_comparison': None,
        'source_first_weak_support': totals,
    }}
    return feature, seal, q


class OriginalPhysicalNegativeReceiptTests(unittest.TestCase):
    def test_untampered_fixture_still_denies_qualifications(self):
        r = audit_receipts(*fixture())
        self.assertFalse(r['production_accepted'])
        self.assertFalse(r['metrics']['hf_auto_tokenizer_model_parity_qualified'])
        self.assertEqual(sum(s['typed_equal_budget'] for s in
                             r['metrics']['retrospective_per_split_top1'].values()), 4)

    def test_forged_source_revision_and_model_digest_fail(self):
        for key, replacement in [('source_original_locomo_sha256',digest('different')),
                                 ('model_safetensors_sha256',digest('other'))]:
            f,s,q=fixture();f[key]=replacement
            with self.subTest(key=key), self.assertRaises(Refused):
                audit_receipts(f,s,q)

    def test_forged_hf_parity_or_future_authority_fails(self):
        for field in ('hf_tokenizer_parity_verified','hf_bert_operator_parity_verified'):
            f,s,q=fixture();f[field]=True
            with self.subTest(field=field), self.assertRaises(Refused):
                audit_receipts(f,s,q)
        f,s,q=fixture();s['independent_future_calendar_windows']=True
        with self.assertRaises(Refused):audit_receipts(f,s,q)

    def test_train_label_ingress_and_invalid_budget_fails(self):
        f,s,q=fixture();f['future_labels_opened_during_encoding']=True
        with self.assertRaises(Refused):audit_receipts(f,s,q)
        f,s,q=fixture();s['training_parameters_paired']=100000
        with self.assertRaises(Refused):audit_receipts(f,s,q)

    def test_original_prediction_digest_and_readback_fails(self):
        f,s,q=fixture();s['predictions'][0]['probabilities']['typed_equal_budget']=0.9
        with self.assertRaises(Refused):audit_receipts(f,s,q)
        f,s,q=fixture();s['physical_reloaded_prediction_check']['verified_predictions']=703
        with self.assertRaises(Refused):audit_receipts(f,s,q)

    def test_weak_support_ceiling_cannot_be_invented_by_head(self):
        f,s,q=fixture();q['metrics']['source_first_weak_support'][1]['hitk']=1
        with self.assertRaises(Refused):audit_receipts(f,s,q)
        f,s,q=fixture();q['metrics']['source_first_weak_support'][1]['questions']=7
        with self.assertRaises(Refused):audit_receipts(f,s,q)

    def test_missing_or_duplicated_question_stratum_fails(self):
        f,s,q=fixture();q['metrics']['source_first_weak_support'].pop()
        with self.assertRaises(Refused):audit_receipts(f,s,q)
        f,s,q=fixture();q['metrics']['source_first_weak_support'][-1] = deepcopy(q['metrics']['source_first_weak_support'][0])
        with self.assertRaises(Refused):audit_receipts(f,s,q)

    def test_no_fabricated_reader_answers_or_strong_rag(self):
        f,s,q=fixture();q['metrics']['original_reader_answers']=44
        with self.assertRaises(Refused):audit_receipts(f,s,q)
        f,s,q=fixture();q['metrics']['strong_hybrid_rag_comparison']={'gain':1.0}
        with self.assertRaises(Refused):audit_receipts(f,s,q)


if __name__ == '__main__':
    unittest.main()
