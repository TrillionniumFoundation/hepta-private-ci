"""Real CPU tensor execution with synthetic evidence; no pretrained/utility claims."""
from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest

import torch

from shared_stem_cell_population import (
    HEAD_PARAMS, WIDTH, STATE, CLASSES, PackedGatedHeads, SmallFrozenStem,
    physical_encode, run_study, study_cases, tensor_sha, unpacked_single_head,
)
from shared_stem_population_review import read_strict, review_reports, stable_digest


class PairedPhysicalCohorts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel={}
        for n in (64,256,1024,4096):
            cls.panel[n]={m:run_study(n,mode=m,seed=7347) for m in
                          ('repeated','distinct','two_scopes')}

    def test_complete_four_physical_cohort_census(self):
        expected={64:8,256:25,1024:102,4096:409}
        for n,k in expected.items():
            p=self.panel[n]
            self.assertEqual(p['repeated']['active_cells'],k)
            self.assertEqual(p['repeated']['head_parameters_total'],n*HEAD_PARAMS)
            self.assertEqual(p['repeated']['head_resident_fp32_tensor_bytes'],n*HEAD_PARAMS*4)
            self.assertEqual(p['distinct']['shared']['encoder_calls'],k)
            self.assertEqual(p['repeated']['shared']['encoder_calls'],4)
            self.assertEqual(p['two_scopes']['shared']['encoder_calls'],8)
            self.assertEqual(p['repeated']['baseline']['encoder_calls'],k)

    def test_real_toy_stem_and_4096_cell_memory_not_deceptively_declared(self):
        r=self.panel[4096]['repeated']
        self.assertEqual(r['head_parameters_total'],39_911_424)
        self.assertEqual(r['head_resident_fp32_tensor_bytes'],159_645_696)
        self.assertEqual(r['stem_frozen_parameters'],147_840)
        self.assertFalse(r['stem_real_pretrained'])
        self.assertFalse(r['real_421m_model_loaded'])
        self.assertEqual(r['stem_actual_physical_calls'],413)
        self.assertFalse(r['actual_4096_real_worker_executed'])

    def test_every_model_does_real_sparse_optimization_preserving_dormant_weights(self):
        for n in (64,256,1024,4096):
            r=self.panel[n]['repeated']
            self.assertTrue(r['dormant_weights_byte_identical'])
            self.assertGreater(r['physically_changed_active_scalars'],0)
            self.assertNotEqual(r['frozen_logits_sha256'],r['learned_logits_sha256'])
            self.assertEqual(r['training_examples'],2*r['active_cells'])
            self.assertEqual(r['physical_head_forward_rows'],7*r['active_cells']+3)
            self.assertGreater(r['head_local_training_wall_ns'],0)

    def test_pinned_stem_weights_and_active_cell_roster_are_matched(self):
        for n,panel in self.panel.items():
            stems={r['stem_original_weight_sha256'] for r in panel.values()}
            active={r['active_indices_sha256'] for r in panel.values()}
            self.assertEqual(len(stems),1)
            self.assertEqual(len(active),1)
            self.assertTrue(all(r['stem_unchanged_after_learning'] for r in panel.values()))
            self.assertEqual(panel['repeated']['original_source_input_sha256'],
                             panel['two_scopes']['original_source_input_sha256'])
            self.assertNotEqual(panel['repeated']['original_source_input_sha256'],
                                panel['distinct']['original_source_input_sha256'])

    def test_learned_weights_also_match_single_head_reference(self):
        for p in self.panel.values():
            for r in p.values():
                self.assertGreaterEqual(r['trained_unpacked_vs_packed_logits_max_abs'],0.)
                self.assertLessEqual(r['trained_unpacked_vs_packed_logits_max_abs'],1e-5)

    def test_forged_frozen_stem_or_different_active_roster_rejected_even_rehashed(self):
        for field in ('stem_original_weight_sha256','active_indices_sha256'):
            p=copy.deepcopy(self.panel[1024])
            p['distinct'][field]='f'*64
            r=p['distinct'];r['report_sha256']=stable_digest({k:v for k,v in r.items() if k!='report_sha256'})
            with self.assertRaisesRegex(ValueError,'unequal research cohort'):
                review_reports(p)

    def test_train_only_toy_loss_honestly_reported_not_quality_claim(self):
        r=self.panel[4096]['repeated']
        self.assertGreater(r['train_loss_initial'],0)
        self.assertGreater(r['train_loss_final'],0)
        self.assertLess(r['train_loss_final'],r['train_loss_initial'])
        for f in ('model_quality_gain_established','independent_future_task_utility',
                  'full_lifecycle_cost_qualified','signed_final_use_verified',
                  'production_authorized'):
            self.assertIs(r[f],False,f)

    def test_no_caching_advantage_on_distinct_inputs(self):
        for n,p in self.panel.items():
            k=p['distinct']['active_cells']
            self.assertEqual(p['distinct']['shared']['cache_hits'],0)
            self.assertEqual(p['distinct']['shared']['encoder_calls'],k)
            self.assertEqual(p['distinct']['stem_actual_physical_calls'],2*k)

    def test_identical_features_cannot_cross_principal_even_when_bytes_match(self):
        for n,p in self.panel.items():
            self.assertEqual(p['repeated']['frozen_logits_sha256'],p['two_scopes']['frozen_logits_sha256'])
            self.assertEqual(p['repeated']['learned_logits_sha256'],p['two_scopes']['learned_logits_sha256'])
            self.assertEqual(p['two_scopes']['shared']['unique_scoped_input_keys'],8)
            self.assertEqual(p['repeated']['shared']['unique_scoped_input_keys'],4)

    def test_native_unpacked_vs_packed_logits_physically_agree(self):
        for p in self.panel.values():
            for r in p.values():
                self.assertLess(r['unpacked_vs_packed_logits_max_abs'],1e-5)
                self.assertEqual(r['shared_vs_uncached_logits_max_abs'],0)

    def test_independent_three_arm_reviewer_declines_all_power_claims(self):
        for n,p in self.panel.items():
            result=review_reports(p)
            self.assertEqual(result['cohort_logical_cells'],n)
            self.assertEqual(result['authority'],'DENY_ALL')
            self.assertFalse(result['actual_pretrained_encoder_verified'])
            self.assertFalse(result['independent_future_task_quality_established'])

    def test_false_4096_pretrained_worker_claim_rejected_even_with_new_digest(self):
        p=copy.deepcopy(self.panel[4096])
        p['repeated']['actual_4096_real_worker_executed']=True
        r=p['repeated'];r['report_sha256']=stable_digest({k:v for k,v in r.items() if k!='report_sha256'})
        with self.assertRaisesRegex(ValueError,'false production'):review_reports(p)

    def test_cannot_fake_positive_savings_for_distinct_sources(self):
        p=copy.deepcopy(self.panel[256]);r=p['distinct']
        r['shared']['encoder_calls']-=1;r['shared']['cache_hits']+=1
        r['stem_actual_physical_calls']-=1
        r['report_sha256']=stable_digest({k:v for k,v in r.items() if k!='report_sha256'})
        with self.assertRaisesRegex(ValueError,'distinct inputs'):review_reports(p)

    def test_false_cross_scope_cache_reuse_denied(self):
        p=copy.deepcopy(self.panel[1024]);r=p['two_scopes']
        r['shared']['encoder_calls']=4;r['shared']['cache_hits']=r['active_cells']-4
        r['stem_actual_physical_calls']=r['active_cells']+4
        r['report_sha256']=stable_digest({k:v for k,v in r.items() if k!='report_sha256'})
        with self.assertRaisesRegex(ValueError,'scope isolation'):review_reports(p)

    def test_inactive_tensor_byte_claim_not_a_genuine_lower_weight_cost(self):
        p=copy.deepcopy(self.panel[4096]);r=p['repeated']
        r['head_resident_fp32_tensor_bytes']=r['trainable_active_parameters']*4
        r['report_sha256']=stable_digest({k:v for k,v in r.items() if k!='report_sha256'})
        with self.assertRaisesRegex(ValueError,'geometry'):review_reports(p)

    def test_missing_arm_or_mutated_existing_report_digest_fails(self):
        p=copy.deepcopy(self.panel[64]);p.pop('distinct')
        with self.assertRaises(ValueError):review_reports(p)
        p=copy.deepcopy(self.panel[64]);p['repeated']['head_parameters_total']+=1
        with self.assertRaises(ValueError):review_reports(p)

    def test_train_step_and_physical_forward_must_be_same_census(self):
        p=copy.deepcopy(self.panel[256]);r=p['repeated']
        r['head_sparse_training_forward_rows']-=25
        r['report_sha256']=stable_digest({k:v for k,v in r.items() if k!='report_sha256'})
        with self.assertRaisesRegex(ValueError,'work census'):review_reports(p)

    def test_independent_review_accepts_true_cache_no_gain_and_one_entry_eviction(self):
        for budget in (0,1536):
            pair={m:run_study(256,mode=m,seed=7347,cache_bytes=budget)
                  for m in ('repeated','distinct','two_scopes')}
            result=review_reports(pair)
            self.assertEqual(result['matched_cache_budget_bytes'],budget)
            self.assertEqual(set(result['measured_call_counts'].values()),{25})
            self.assertFalse(result['production_authorized'])

    def test_partial_cache_savings_does_not_cross_principal(self):
        pair={m:run_study(256,mode=m,seed=7347,cache_bytes=6144)
              for m in ('repeated','distinct','two_scopes')}
        result=review_reports(pair)
        self.assertEqual(result['measured_call_counts'],
                         {'repeated':4,'distinct':25,'two_scopes':25})

    def test_unfair_cache_budget_between_arms_fails_independent_review(self):
        pair=copy.deepcopy(self.panel[256]);r=pair['distinct']
        r['shared']['cache_budget_bytes']=131072
        r['report_sha256']=stable_digest({k:v for k,v in r.items() if k!='report_sha256'})
        with self.assertRaisesRegex(ValueError,'unmatched cache resource'):
            review_reports(pair)

    def test_report_original_seeded_weight_identity_preserved(self):
        a=run_study(64,seed=7347,mode='repeated')
        b=run_study(64,seed=7347,mode='repeated')
        self.assertEqual(a['frozen_logits_sha256'],b['frozen_logits_sha256'])
        self.assertEqual(a['learned_logits_sha256'],b['learned_logits_sha256'])
        self.assertNotEqual(a['complete_study_wall_ns'],0)


class CohortFailureCases(unittest.TestCase):
    def test_register_only_64_256_1024_4096_avoid_fake_10t_geometry(self):
        for c in (0,1,63,65,4097,True,'4096'):
            with self.subTest(c=c),self.assertRaises(ValueError):run_study(c)

    def test_no_invalid_seed_scope_or_capacity(self):
        for val in (0,-1,True,2**32,'7347'):
            with self.assertRaises(ValueError):run_study(64,seed=val)
        for capacity in (-1,True,256*1024*1024+1):
            with self.assertRaises(ValueError):run_study(64,cache_bytes=capacity)
        with self.assertRaises(ValueError):run_study(64,mode='unknown')

    def test_per_borrow_callback_has_real_rejection(self):
        cases=study_cases(torch.arange(8),seed=7347,mode='repeated')
        provider=SmallFrozenStem()
        checks=[]
        def callback(idx,group,key,scope):
            checks.append(idx)
            return len(checks)<=5
        with self.assertRaisesRegex(ValueError,'per-cell access'):
            physical_encode(cases,provider,cache_bytes=32000,allow=callback)
        self.assertEqual(len(checks),6)
        self.assertEqual(provider.calls,4)

    def test_per_borrow_callback_cannot_mutate_context_and_pass(self):
        cases=study_cases(torch.arange(8),seed=7347,mode='repeated')
        def corrupt(idx,group,key,ctx):
            ctx['authority_epoch']+=1
            return True
        with self.assertRaisesRegex(ValueError,'context modified'):
            physical_encode(cases,SmallFrozenStem(),cache_bytes=32000,allow=corrupt)

    def test_tiny_cache_reports_evictions_without_impossible_hits(self):
        cases=study_cases(torch.arange(16),seed=7347,mode='repeated')
        shared,metrics=physical_encode(cases,SmallFrozenStem(),cache_bytes=WIDTH*4,allow=lambda *args:True)
        self.assertEqual(shared.shape,(16,WIDTH))
        self.assertEqual(metrics['encoder_calls'],16)
        self.assertEqual(metrics['cache_hits'],0)
        self.assertGreater(metrics['cache_evictions'],0)
        self.assertLessEqual(metrics['peak_cache_tensor_bytes'],WIDTH*4)

    def test_9_744_head_parameter_mathematical_contract(self):
        weights=PackedGatedHeads(64,7347)
        self.assertEqual(weights.param_count,64*9744)
        self.assertEqual(weights.weights['down'].shape,(64,8,384))
        self.assertEqual(weights.weights['gate'].shape,(64,8,64))
        self.assertEqual(weights.weights['up'].shape,(64,384,8))
        self.assertEqual(weights.weights['output'].shape,(64,8,384))

    def test_single_cell_module_math_matches_packed_torch(self):
        pop=PackedGatedHeads(64,7347)
        idx=torch.tensor([1,10,40],dtype=torch.int64)
        x=torch.randn((3,WIDTH),generator=torch.Generator().manual_seed(1))
        st=torch.randn((3,STATE),generator=torch.Generator().manual_seed(2))
        packed=pop.predict(pop.rows(idx),x,st)
        for slot,cell in enumerate(idx.tolist()):
            manual=unpacked_single_head(pop.weights,x[slot],st[slot],cell)
            self.assertTrue(torch.allclose(packed[slot],manual,atol=1e-5,rtol=0))

    def test_full_head_bank_has_no_change_to_inactive_bytes_under_sgd(self):
        pop=PackedGatedHeads(64,7347)
        ids=torch.tensor([1,3,7,10,17,39,51,63])
        x=torch.randn((8,WIDTH),generator=torch.Generator().manual_seed(3))
        state=torch.randn((8,STATE),generator=torch.Generator().manual_seed(4))
        before=pop.dormant_digest(ids)
        summary=pop.fit_sparse(ids,x,state,torch.arange(8)%CLASSES,steps=2)
        self.assertEqual(before,pop.dormant_digest(ids))
        self.assertTrue(summary['dormant_weights_byte_identical'])
        self.assertGreater(summary['physically_changed_active_scalars'],0)

    def test_model_gradient_never_reaches_shared_stem(self):
        stem=SmallFrozenStem()
        self.assertFalse(any(p.requires_grad for p in stem.parameters()))
        feature=stem(torch.zeros(WIDTH))
        self.assertFalse(feature.requires_grad)
        pop=PackedGatedHeads(64,7347)
        out=pop.predict(pop.rows(torch.arange(8)),feature.repeat(8,1),torch.zeros((8,STATE)))
        self.assertFalse(out.requires_grad)

    def test_bad_feature_not_misreported_as_valid_model_forward(self):
        x=torch.zeros((WIDTH,),dtype=torch.float64)
        with self.assertRaises(ValueError):SmallFrozenStem()(x)
        with self.assertRaises(ValueError):SmallFrozenStem()(torch.zeros(12))

    def test_independent_stdlib_reader_detects_duplicate_json_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'input.json'
            path.write_text('{"schema":1,"schema":2}')
            with self.assertRaises(ValueError):read_strict(path)

    def test_independent_stdlib_reader_rejects_symlink_and_nonfinite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); original=root/'original.json'
            original.write_text('{"value":NaN}')
            with self.assertRaises(ValueError):read_strict(original)
            link=root/'link.json';link.symlink_to(original)
            with self.assertRaises(OSError):read_strict(link)

if __name__=='__main__':unittest.main()
