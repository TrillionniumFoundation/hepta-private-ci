"""Physical CPU reverse-autograd profiler, sealed costs and adversarial audit.

The 147,840-parameter randomly initialized fake Stem is a mechanism fixture,
not a real public Granite97 weight execution or independent prospective task.
"""
from __future__ import annotations
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import torch

import p1_real_granite_cohort as p1
import p1_real_granite_review as p1review
import p2_real_cell_split as p2
import p2_train_sparse_equal_compute as top1
import p2_backward_cost_profiler as producer
import p2_backward_cost_profile_review as audit
from test_p1_real_granite_cohort import FakePhysicalStem,setup_fixture


class CostProfileCausality(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel,cls.train,cls.blind,cls.labels,cls.panel_sha=setup_fixture()
        torch.manual_seed(7347)
        cls.stem=FakePhysicalStem()
        with patch.object(p1,'PANEL_SHA',cls.panel_sha),patch.object(p1review,'PANEL_SHA',cls.panel_sha):
            cls.p2=p2.execute(cls.train,cls.blind,cls.stem,seed=7347)
            cls.previous=top1.execute(cls.train,cls.blind,cls.stem,seed=7347,parent_p2=cls.p2)
            cls.profile=producer.execute(cls.train,cls.blind,cls.stem,cls.p2,cls.previous,real=False)
            cls.review=audit.review(cls.panel,cls.train,cls.blind,cls.labels,
                                     cls.p2,cls.previous,cls.profile)

    def tampered(self,edit):
        candidate=copy.deepcopy(self.profile)
        edit(candidate)
        candidate['report_sha256']=top1.digest({k:v for k,v in candidate.items() if k!='report_sha256'})
        return candidate

    def score(self,profile=None,p2_report=None,previous=None,gold=None):
        with patch.object(p1review,'PANEL_SHA',self.panel_sha):
            return audit.review(self.panel,self.train,self.blind,gold or self.labels,
                                p2_report or self.p2,previous or self.previous,
                                profile or self.profile)

    def test_four_fully_profiler_replayed_source_bound_arms(self):
        self.assertEqual(tuple(self.profile['profiled_arms']),producer.REGISTERED_ARMS)
        self.assertEqual(set(self.review['arms']),set(producer.REGISTERED_ARMS))
        self.assertEqual(self.profile['physical_encoder_forward_calls_in_profile_job'],224)
        for name,arm in self.profile['profiled_arms'].items():
            self.assertLessEqual(arm['original_result_logits_max_abs'],1e-6)
            self.assertEqual(arm['original_final_weights_sha256'],
                             self.previous['compared_arms'][name]['final_weights_sha256'])

    def test_partial_observed_flops_are_NOT_complete_backward_flops(self):
        self.assertFalse(self.profile['complete_backward_flops_verified'])
        self.assertFalse(self.profile['equal_total_training_compute_verified'])
        self.assertTrue(self.review['profilers_report_partial_flops_only'])
        self.assertFalse(self.review['complete_cost_and_energy_certified'])
        for arm in self.review['arms'].values():
            self.assertFalse(arm['complete_total_compute_matched'])
            self.assertFalse(arm['cost_total_forward_backward_verified'])
            self.assertGreater(arm['registered_partial_cpu_profiler_flops'],0)

    def test_one_active_matched_rows_does_not_match_autograd_operator_work(self):
        s=self.profile['profiled_arms']['single_active']
        f=self.profile['profiled_arms']['fixed_top1']
        a=self.profile['profiled_arms']['adaptive_top1']
        self.assertEqual(s['train_selected_expert_forward_rows'],[3840,0])
        self.assertEqual(sum(f['train_selected_expert_forward_rows']),3840)
        self.assertEqual(sum(a['train_selected_expert_forward_rows']),3840)
        self.assertEqual(s['registered_expert_forward_linear_mac'],f['registered_expert_forward_linear_mac'])
        self.assertGreater(f['recorded_autograd_function_nodes'],s['recorded_autograd_function_nodes'])
        self.assertGreater(f['recorded_route_kernel_calls'],s['recorded_route_kernel_calls'])
        self.assertIn('autograd::engine::evaluate_function: MmBackward0',f['operator_census'])

    def test_frozen_zero_backward_and_no_optimizer_updates(self):
        frozen=self.profile['profiled_arms']['frozen_single']
        self.assertEqual(frozen['recorded_autograd_function_nodes'],0)
        self.assertEqual(frozen['train_updates'],0)
        self.assertEqual(frozen['train_selected_expert_forward_rows'],[0,0])

    def test_weight_residency_and_old_logits_unchanged(self):
        for name in self.profile['profiled_arms']:
            self.assertEqual(self.profile['profiled_arms'][name]['original_final_weights_sha256'],
                             self.previous['compared_arms'][name]['final_weights_sha256'])
        self.assertTrue(self.review['previous_p2_training_quality_claims_unchanged'])

    def test_profile_no_real_stem_or_future_source_claims(self):
        self.assertFalse(self.profile['pretrained_model_loaded_in_profile_job'])
        self.assertFalse(self.profile['original_model_load_is_incremental_cost'])
        self.assertFalse(self.profile['source_model_publisher_signed'])
        self.assertFalse(self.profile['future_source_family_generalization_verified'])
        self.assertFalse(self.review['production_promotion_permitted'])

    def test_run_requires_original_source_and_refuses_faked_real_weights(self):
        with patch.object(p1,'PANEL_SHA',self.panel_sha):
            with self.assertRaisesRegex(ValueError,'cannot relabel fixture'):
                producer.execute(self.train,self.blind,self.stem,self.p2,self.previous,real=True)

    def test_run_rejects_wrong_train_row_label_or_source_panel(self):
        bad=copy.deepcopy(self.train)
        bad['rows'][0]['label']=1-bad['rows'][0]['label']
        with patch.object(p1,'PANEL_SHA',self.panel_sha):
            with self.assertRaises(ValueError):
                producer.execute(bad,self.blind,self.stem,self.p2,self.previous)

    def test_run_rejects_original_model_drift(self):
        prior=copy.deepcopy(self.p2)
        prior['frozen_model_weights_sha256']='f'*64
        prior['report_sha256']=top1.digest({k:v for k,v in prior.items() if k!='report_sha256'})
        with patch.object(p1,'PANEL_SHA',self.panel_sha):
            with self.assertRaises(ValueError):
                producer.execute(self.train,self.blind,self.stem,prior,self.previous)

    def test_run_rejects_rehashed_wrong_original_trained_report(self):
        prior=copy.deepcopy(self.previous)
        prior['model_parameter_count']+=1
        prior['report_sha256']=top1.digest({k:v for k,v in prior.items() if k!='report_sha256'})
        with patch.object(p1,'PANEL_SHA',self.panel_sha):
            with self.assertRaises(ValueError):
                producer.execute(self.train,self.blind,self.stem,self.p2,prior)

    def test_refuse_rehashed_false_equal_backward_flops_promotion(self):
        candidate=self.tampered(lambda d:d.update(equal_total_training_compute_verified=True))
        with self.assertRaisesRegex(ValueError,'unsupported'):
            self.score(candidate)

    def test_refuse_rehashed_false_production_latency_claim(self):
        candidate=self.tampered(lambda d:d['profiled_arms']['fixed_top1'].update(
            instrumented_wall_is_production_latency=True))
        with self.assertRaises(ValueError):self.score(candidate)

    def test_refuse_rehashed_fake_publisher_signature(self):
        candidate=self.tampered(lambda d:d.update(source_model_publisher_signed=True))
        with self.assertRaises(ValueError):self.score(candidate)

    def test_refuse_missing_operator_rehash(self):
        candidate=self.tampered(lambda d:d['profiled_arms']['single_active']['operator_census'].pop('aten::mm'))
        with self.assertRaises(ValueError):self.score(candidate)

    def test_refuse_rehashed_operator_count_change_without_consistent_summary(self):
        # An offline reviewer cannot authenticate a self-consistently forged
        # operator counter. It checks the summed arithmetic and seal only.
        # Total mm count is not attested by a second hardware profiler; only
        # internally consistent numeric aggregation can be checked offline.
        # Reject rewriting FLOP totals rather than assert unverifiable event counts.
        candidate=self.tampered(lambda d:d['profiled_arms']['fixed_top1']['operator_census']['aten::mm'].update(partial_estimated_flops=1234))
        with self.assertRaisesRegex(ValueError,'inconsistent'):
            self.score(candidate)

    def test_refuse_fake_total_backprop_coverage_even_if_rehashed(self):
        candidate=self.tampered(lambda d:d['profiled_arms']['adaptive_top1'].update(
            operator_flops_equal_total_backward_flops=True))
        with self.assertRaises(ValueError):self.score(candidate)

    def test_refuse_wrong_source_identity_with_fresh_hash(self):
        candidate=self.tampered(lambda d:d.update(original_panel_sha256='f'*64))
        with self.assertRaisesRegex(ValueError,'model'):
            self.score(candidate)

    def test_refuse_swapped_original_trained_tensors(self):
        original=copy.deepcopy(self.previous)
        original['compared_arms']['fixed_top1']['final_weights_sha256']='f'*64
        original['report_sha256']=top1.digest({k:v for k,v in original.items() if k!='report_sha256'})
        with self.assertRaises(ValueError):self.score(previous=original)

    def test_refuse_false_profiled_model_type(self):
        candidate=self.tampered(lambda d:d.update(pretrained_model_loaded_in_profile_job=True))
        with self.assertRaises(ValueError):self.score(candidate)

    def test_refuse_false_matched_training_steps(self):
        candidate=self.tampered(lambda d:d['profiled_arms']['single_active'].update(train_updates=39))
        with self.assertRaises(ValueError):self.score(candidate)

    def test_refuse_false_migration_copy_work(self):
        candidate=self.tampered(lambda d:d['profiled_arms']['adaptive_top1'].update(migration_fp32_copy_bytes=0))
        if self.previous['compared_arms']['adaptive_top1']['migration_copied_fp32_bytes']:
            with self.assertRaises(ValueError):self.score(candidate)
        else:
            candidate=self.tampered(lambda d:d['profiled_arms']['adaptive_top1'].update(migration_fp32_copy_bytes=4))
            with self.assertRaises(ValueError):self.score(candidate)

    def test_reject_test_labels_to_producer(self):
        bad=copy.deepcopy(self.blind)
        bad['rows'][0]['label']=0
        with patch.object(p1,'PANEL_SHA',self.panel_sha):
            with self.assertRaises(ValueError):
                producer.execute(self.train,bad,self.stem,self.p2,self.previous)

    def test_tamper_cost_report_optimistic_signed_performance(self):
        candidate=self.tampered(lambda d:d.update(complete_backward_flops_verified=True))
        with self.assertRaises(ValueError):self.score(candidate)

    def test_missing_entire_arm_rejected(self):
        candidate=self.tampered(lambda d:d['profiled_arms'].pop('single_active'))
        with self.assertRaises(ValueError):self.score(candidate)

    def test_unauthorized_new_field_rejected(self):
        candidate=self.tampered(lambda d:d.update(some_new_authority='GRANT'))
        with self.assertRaises(ValueError):self.score(candidate)

    def test_early_opened_wrong_real_human_label_fails_source_review(self):
        wrong=copy.deepcopy(self.labels)
        wrong['rows'][0]['label']^=1
        wrong['seal_id']=top1.digest({k:v for k,v in wrong.items() if k!='seal_id'})
        with self.assertRaises(ValueError):self.score(gold=wrong)

    def test_profile_journal_rejects_duplicate_json_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'dup.json'
            path.write_text('{"a":1,"a":2}')
            with self.assertRaisesRegex(ValueError,'duplicate JSON'):
                audit.read(path)

    def test_profile_journal_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            actual=Path(tmp)/'real.json';actual.write_text('{"a":123,"b":234}')
            link=Path(tmp)/'link.json';link.symlink_to(actual)
            with self.assertRaises(OSError):audit.read(link)

    def test_profile_journal_rejects_nonfinite_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'bad.json';path.write_text('{"x":NaN,"y":34}')
            with self.assertRaises(ValueError):audit.read(path)

    def test_some_kernel_names_have_no_flop_estimate(self):
        a=self.profile['profiled_arms']['single_active']
        self.assertIn('aten::mm',a['operator_census'])
        self.assertIn('autograd::engine::evaluate_function: MmBackward0',a['operator_census'])
        self.assertEqual(a['operator_census']['aten::silu']['partial_estimated_flops'],0)
        self.assertGreater(a['registered_aten_self_cpu_us'],a['registered_flop_covered_self_cpu_us'])

    def test_profiler_overhead_is_not_claimed_as_e2e_speedup(self):
        for x in self.review['arms'].values():
            self.assertGreater(x['instrumented_wall_ns'],0)
            self.assertGreater(x['partial_aten_flop_ratio_vs_single_active'],0)
        self.assertTrue(self.review['same_forward_expert_rows_is_not_full_equal_training_compute'])

if __name__=='__main__':unittest.main()
