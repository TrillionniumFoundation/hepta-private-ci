"""Strict synthetic-receipt attacks on P0 cost; no real pretrained model claim."""
from __future__ import annotations

import copy
import types
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from p0_multirc_semantic_material import Invalid, canonical, sha
from p0_encoding_cost_frontier import review, SCHEMA, _split_cost_profile
from p0_multirc_semantic_execute import run
from test_p0_multirc_semantic import setup
from test_p0_question_only_matched import match_fixture, fake_vectors


def mock_all(fit,blind):
    """These are SYNTHETIC external reports, never actual-pretrained outcomes."""
    reports=match_fixture(fit,blind,'all')
    rows=fit['cases']+blind['cases']
    tokens={r['case_id']:(120 if r['condition']=='original' else 24) for r in rows}
    for model in ('granite_97m_r2','mmbert_small','embeddinggemma_2_text'):
        profile=reports[model]['complete_source_profiles']
        profile['physical_token_counts_by_case']=dict(tokens)
        profile['source_token_counts_sha256']=sha(canonical(tokens))
        profile['encoder_ms_by_case']=dict(profile['physical_encoder_ms_by_case'])
    return reports


class EvidenceCostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source_train,cls.source_validation,cls.fit,cls.blind,cls.owner=setup()

    def setUp(self):
        self.reports=mock_all(self.fit,self.blind)

    def evaluate(self,reports=None,**kwargs):
        return review(self.fit,self.blind,self.owner,self.source_train,self.source_validation,
                      self.reports if reports is None else reports,**kwargs)

    def negative(self,fn):
        r=copy.deepcopy(self.reports)
        fn(r)
        with self.assertRaises(Invalid):self.evaluate(r)

    def test_real_original_labels_and_cost_not_selected(self):
        o=self.evaluate()
        self.assertEqual(o['schema'],SCHEMA)
        self.assertEqual(set(o['profile']),set(self.reports))
        self.assertFalse(o['winner_selected'])
        self.assertFalse(o['result_quality_after_cost_superiority_proven'])
        self.assertFalse(o['physical_measurements_independently_attested'] if 'physical_measurements_independently_attested' in o else False)
        self.assertEqual(o['observational_human_label_results']['granite_97m_r2']['source_groups'],8)
        self.assertEqual(o['observational_human_label_results']['granite_97m_r2']['independent_confirmatory_future_windows'],0)

    def test_standalone_counts_each_load_not_double_joint(self):
        a=self.evaluate()['profile']['granite_97m_r2']
        self.assertEqual(a['physical_input_counts'],{'original':96,'question_only':96})
        self.assertEqual(a['observed_token_counts']['evidence_sum'],120*96)
        self.assertEqual(a['observed_token_counts']['question_only_sum'],24*96)
        self.assertTrue(a['same_model_load_counted_once_in_joint_process'])
        self.assertTrue(a['separate_strategy_model_load_charged_once_each'])
        self.assertEqual(a['reported_encoding_ms']['all_views_once'],
                         a['reported_encoding_ms']['evidence']+a['reported_encoding_ms']['question_only'])
        self.assertGreater(a['standalone_cold_cost_lower_bound_ms']['evidence'],
                           a['reported_head_training_ms']['evidence'])
        self.assertFalse(a['full_lifecycle_cost_known'])

    def test_original_scorer_bytes_replayed(self):
        from p0_question_only_review import review as prior
        original=prior(self.fit,self.blind,self.owner,self.source_train,self.source_validation,self.reports)
        newer=self.evaluate(matched_record=original)
        self.assertEqual(newer['prior_matched_score_sha256'],sha(canonical(original)))

    def test_rejects_changed_scored_original_bytes(self):
        from p0_question_only_review import review as prior
        o=prior(self.fit,self.blind,self.owner,self.source_train,self.source_validation,self.reports)
        o['matched_models']['mmbert_small']['learned_evidence_versus_separately_trained_question_only']['source_passages']=17
        with self.assertRaises(Invalid):self.evaluate(matched_record=o)

    def test_rejects_missing_one_original_model(self):
        self.negative(lambda r:r.pop('embeddinggemma_2_text'))

    def test_rejects_missing_physical_tokens(self):
        self.negative(lambda r:r['granite_97m_r2']['complete_source_profiles'].pop('physical_token_counts_by_case'))

    def test_rejects_dropped_one_physical_token_count(self):
        def change(r):
            m=r['mmbert_small']['complete_source_profiles']['physical_token_counts_by_case']
            m.pop(next(iter(m)))
        self.negative(change)

    def test_rejects_extra_token_id(self):
        self.negative(lambda r:r['granite_97m_r2']['complete_source_profiles']['physical_token_counts_by_case'].update(forged=10))

    def test_rejects_forged_single_token_with_old_hash(self):
        def change(r):
            m=r['mmbert_small']['complete_source_profiles']['physical_token_counts_by_case']
            m[next(iter(m))]+=1
        self.negative(change)

    def test_rejects_float_typed_token_even_rehashed(self):
        def change(r):
            p=r['embeddinggemma_2_text']['complete_source_profiles']
            k=next(iter(p['physical_token_counts_by_case']))
            p['physical_token_counts_by_case'][k]=12.0
            p['source_token_counts_sha256']=sha(canonical(p['physical_token_counts_by_case']))
        self.negative(change)

    def test_rejects_over_limit_512_even_rehashed(self):
        def change(r):
            p=r['embeddinggemma_2_text']['complete_source_profiles']
            k=next(iter(p['physical_token_counts_by_case']))
            p['physical_token_counts_by_case'][k]=513
            p['source_token_counts_sha256']=sha(canonical(p['physical_token_counts_by_case']))
        self.negative(change)

    def test_rejects_renamed_encoder_time_census(self):
        def change(r):
            p=r['granite_97m_r2']['complete_source_profiles']['encoder_ms_by_case']
            p.pop(next(iter(p)))
        self.negative(change)

    def test_rejects_counterfactual_encoder_time_alias(self):
        def change(r):
            p=r['mmbert_small']['complete_source_profiles']['encoder_ms_by_case']
            k=next(iter(p));p[k]*=2
        self.negative(change)

    def test_rejects_unphysical_declared_token_time(self):
        def change(r):
            p=r['granite_97m_r2']['complete_source_profiles']
            k=next(iter(p['physical_encoder_ms_by_case']))
            p['physical_encoder_ms_by_case'][k]=float('nan')
            p['encoder_ms_by_case'][k]=float('nan')
        self.negative(change)

    def test_rejects_fabricated_extra_api_requests(self):
        self.negative(lambda r:r['mmbert_small']['complete_source_profiles'].update(physical_encoder_api_requests=99999))

    def test_rejects_impossible_local_process_time(self):
        self.negative(lambda r:r['embeddinggemma_2_text'].update(local_process_wall_ms=.1))

    def test_rejects_extra_serving_result_id(self):
        def change(r):
            p=r['granite_97m_r2']['control']['trained_head']['predictions'][0]
            p['case_id']='d'*32
        self.negative(change)

    def test_rejects_laya_as_fake_trained_head(self):
        self.negative(lambda r:r['laya421_nochange'].update(matched_question_only_control={}))

    def test_no_assumption_equal_text_encoder_compute(self):
        a=self.evaluate()
        self.assertFalse(a['reported_encoder_compute_parity'])
        self.assertTrue(a['equal_head_training_updates_do_not_imply_equal_total_compute'])
        self.assertFalse(a['prospective_future_windows_verified'])

    def test_actual_torch_run_records_precise_token_inventory(self):
        # Import torch BEFORE patch.dict(sys.modules): a lazily imported native
        # extension can outlive a temporary sys.modules snapshot and fail reimport.
        import torch
        torch_identity = sys.modules['torch']
        rows=self.fit['cases']+self.blind['cases'];vectors=fake_vectors(rows,256)
        tokens={r['case_id']:(112 if r['condition']=='original' else 20) for r in rows}
        def fake_encode(inputs,model,a,b,c):
            self.assertEqual([r['case_id'] for r in inputs],[r['case_id'] for r in rows])
            return vectors,tokens,{r['case_id']:'a'*64 for r in rows},{
                'local_model_api_requests':len(rows),'load_ms':3.,
                'encode_ms_by_case':{r['case_id']:.02 for r in rows}}
        mod=types.ModuleType('e1_public_triplet_real_cpu');mod.encode_pretrained=fake_encode
        args=SimpleNamespace(compact_checkout='reviewed',gemma_checkout='reviewed',gemma_manifest='pinned')
        # Replace only the narrow source module. Patching all of sys.modules
        # snapshots/restores lazily loaded torch._inductor Python modules, but
        # does NOT unregister their native torch.library operators. That would
        # make later tests fail with a duplicate TORCH_LIBRARY registration.
        key='e1_public_triplet_real_cpu'
        missing=object()
        previous=sys.modules.get(key,missing)
        sys.modules[key]=mod
        try:
            out=run(self.fit,self.blind,'embeddinggemma_2_text',args)
        finally:
            if previous is missing:
                sys.modules.pop(key,None)
            else:
                sys.modules[key]=previous
        self.assertIs(sys.modules['torch'],torch_identity)
        profile=out['complete_source_profiles']
        self.assertEqual(profile['physical_token_counts_by_case'],tokens)
        self.assertEqual(profile['source_token_counts_sha256'],sha(canonical(tokens)))
        self.assertTrue(out['matched_question_only_control']['additional_encoder_forwards']==0)
        self.assertFalse(out['production_promotion_permitted'])


if __name__=='__main__':
    unittest.main()
