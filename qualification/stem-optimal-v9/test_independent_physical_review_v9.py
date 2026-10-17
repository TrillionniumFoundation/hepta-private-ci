"""Research-only independent reader adversarial tests (no model download)."""
import copy
import sys
from pathlib import Path
import types
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).parent))
import test_physical_selective_v9 as fixtures

# Independent review code imports only independent historical reviewer types.
source_review=types.ModuleType('stem_hard_charge_review_v3')
historical=types.ModuleType('paired_review_v5')
historical.SOURCE_PLAN_SHA='original-fixed-source'
lexical=types.ModuleType('cheap_lexical_review_v4')
with patch.dict(sys.modules,{'stem_hard_charge_review_v3':source_review,
                             'paired_review_v5':historical,
                             'cheap_lexical_review_v4':lexical}):
    import independent_physical_review_v9 as verify


def receipt(mode, source, cheap, old, materials):
    selected,_=verify.rerank(cheap,source)
    ids=[r for r in source['heldout'] if mode=='full' or r['case_id'] in selected]
    n=len(ids)
    return {
        'schema':verify.SCHEMA,'mode':mode,'candidate':'granite47',
        'source_plan_sha256':source['source_plan_sha256'],
        'authority':'DENY_ALL','disposition':'HOLD_NO_GO',
        'production_authorized':False,'stem_winner_verified':False,
        'cell_split_authorized':False,'future_windows':0,'source_independent_families':1,
        'full_lifecycle_savings_qualified':False,
        'hardware_meter_independently_attested':False,
        'original_v3_label_exposure_prior_to_design':True,
        'trial_separate_fresh_process':True,
        'model_repo':old['model_repo'],'model_revision':old['model_revision'],
        'actual_weight_sha256':old['actual_weight_sha256'],
        'material_sha256':verify.sha(verify.canonical(materials)),
        'source_sha256':verify.sha(verify.canonical(source)),
        'cheap_receipt_sha256':verify.sha(verify.canonical(cheap)),
        'original_receipt_sha256':verify.sha(verify.canonical(old)),
        'selected_case_ids':selected,
        'head_parameters':27656,'optimizer_steps':100,
        'initial_head_sha256':old['initial_head_sha256'],
        'trained_head_sha256':old['trained_head_sha256'],
        'trained_head_byte_identical_to_original':True,
        'active_case_ids':[r['case_id'] for r in ids],
        'rows':[{'case_id':r['case_id'],'source_sha256':r['source_sha256'],
                 'probabilities':[0.8,0.1,0.06,0.04]} for r in ids],
        'cost':{'model_load_wall_seconds':0.1,'cheap_wall_seconds':0.01,
                'full_encoder_frozen_train_rows':64,'physically_encoded_heldout_rows':n,
                'physically_executed_encoder_sequences':64+n,
                'actual_model_forward_hook_calls':5 if mode=='selective' else 6,
                'frozen_train_forward_batches':4,
                'heldout_forward_batches':1 if mode=='selective' else 2,
                'feature_encode_wall_seconds':0.2,'head_training_wall_seconds':0.01,
                'elapsed_cpu_seconds':1.1,'elapsed_wall_seconds':1.5,
                'process_peak_rss_bytes':100000,'energy_joules':None,'p99_latency_ms':None},
    }


class IndependentPhysicalReviewTests(unittest.TestCase):
    def setUp(self):
        self.source,self.cheap,self.old,self.materials=fixtures.fixture()
        self.patch=patch.object(verify,'SOURCE_SHA',self.source['source_plan_sha256'])
        self.patch.start();self.addCleanup(self.patch.stop)
        self.selected=receipt('selective',self.source,self.cheap,self.old,self.materials)
        self.full=receipt('full',self.source,self.cheap,self.old,self.materials)

    def test_exact_active_case_count_and_frozen_original_scores(self):
        got=verify.checked_run(self.selected,'selective',self.source,self.cheap,
                               self.old,self.materials,self.selected['selected_case_ids'])
        self.assertEqual(len(got),8)
        got=verify.checked_run(self.full,'full',self.source,self.cheap,
                               self.old,self.materials,self.selected['selected_case_ids'])
        self.assertEqual(len(got),32)

    def test_forged_8_without_actual_model_hook_fails(self):
        bad=copy.deepcopy(self.selected)
        bad['cost']['actual_model_forward_hook_calls']=0
        with self.assertRaisesRegex(ValueError,'forward hook'):
            verify.checked_run(bad,'selective',self.source,self.cheap,
                               self.old,self.materials,self.selected['selected_case_ids'])

    def test_forged_training_or_runtime_credential_fails(self):
        for mutation in (
            lambda r:r.__setitem__('production_authorized',True),
            lambda r:r.__setitem__('head_parameters',0),
            lambda r:r.__setitem__('trained_head_byte_identical_to_original',False),
            lambda r:r['cost'].__setitem__('energy_joules',0.1),
            lambda r:r['cost'].__setitem__('p99_latency_ms',0.2),
        ):
            bad=copy.deepcopy(self.selected);mutation(bad)
            with self.assertRaises(ValueError):
                verify.checked_run(bad,'selective',self.source,self.cheap,
                                   self.old,self.materials,self.selected['selected_case_ids'])

    def test_tampered_original_probability_and_case_drift_fail(self):
        for mutation in (
            lambda r:r['rows'][0]['probabilities'].__setitem__(0,.4),
            lambda r:r['rows'][0].__setitem__('source_sha256','f'*64),
            lambda r:r['active_case_ids'].append('new-case'),
        ):
            bad=copy.deepcopy(self.selected);mutation(bad)
            with self.assertRaises(ValueError):
                verify.checked_run(bad,'selective',self.source,self.cheap,
                                   self.old,self.materials,self.selected['selected_case_ids'])

    def test_mock_original_publisher_handoff_always_denies_production(self):
        """Fixture scoring is not independent publisher qualification or model authority."""
        gold = {case['case_id']: 0 for case in self.source['heldout']}
        fake_original = types.SimpleNamespace(FIXED_SHA={'train':'fixture','test':'fixture'})
        with patch.object(verify.publisher, 'original', fake_original, create=True), \
             patch.object(verify.publisher, 'reconstruct',
                          return_value=({'train': self.source['train'],
                                         'heldout': self.source['heldout']}, gold), create=True), \
             patch.object(verify.lexical, 'review_original',
                          return_value={'independent_algorithm_replay':True,
                                        'publisher_original_sha_verified':True}, create=True):
            result=verify.review(b'synthetic-train', b'synthetic-test', self.source,
                                 self.cheap, self.old, self.materials,
                                 self.selected, self.full)
        self.assertEqual(result['actual_selective_forward_hook_calls'], 5)
        self.assertEqual(result['actual_full_forward_hook_calls'], 6)
        self.assertEqual(result['physical_selective']['n'],32)
        self.assertFalse(result['full_lifecycle_savings_qualified'])
        self.assertFalse(result['production_authorized'])
        self.assertEqual(result['disposition'],'HOLD_NO_GO')

    def test_original_cheap_routing_and_score_are_deterministic(self):
        expected,cheap=verify.rerank(self.cheap,self.source)
        self.assertEqual(expected,self.selected['selected_case_ids'])
        gold={cid:0 for cid in cheap}
        scored=verify.score(cheap,gold)
        self.assertEqual(scored['n'],32)
        self.assertGreaterEqual(scored['brier'],0)


if __name__=='__main__':unittest.main()
