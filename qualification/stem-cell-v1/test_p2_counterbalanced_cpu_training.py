"""Counterbalanced physical re-training, source fidelity, cost and tamper tests."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import torch

import p1_real_granite_cohort as p1
import p1_real_granite_review as p1review
import p2_real_cell_split as p2
import p2_train_sparse_equal_compute as top1
import p2_backward_cost_profiler as prior
import p2_counterbalanced_cpu_training as prod
import p2_counterbalanced_cpu_training_review as audit
from test_p1_real_granite_cohort import setup_fixture, FakePhysicalStem


class PhysicalCrossoverSource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel,cls.train,cls.blind,cls.labels,cls.panel_sha=setup_fixture()
        torch.manual_seed(7347)
        cls.backend=FakePhysicalStem()
        with patch.object(p1,'PANEL_SHA',cls.panel_sha), patch.object(p1review,'PANEL_SHA',cls.panel_sha):
            cls.old=p2.execute(cls.train,cls.blind,cls.backend,seed=7347)
            cls.learned=top1.execute(cls.train,cls.blind,cls.backend,seed=7347,parent_p2=cls.old)
            cls.profiler=prior.execute(cls.train,cls.blind,cls.backend,cls.old,cls.learned,real=False)
            cls.physical=prod.execute(cls.train,cls.blind,cls.backend,cls.old,cls.learned,
                                      real=False,rounds=8,crossover_seed=20261015)
            cls.score=audit.review(cls.panel,cls.train,cls.blind,cls.labels,
                                   cls.old,cls.learned,cls.profiler,cls.physical)

    def review_trace(self, trace=None, *, original=None, learned=None, profiler=None, labels=None):
        with patch.object(p1review,'PANEL_SHA',self.panel_sha):
            return audit.review(self.panel,self.train,self.blind,labels if labels is not None else self.labels,
                                original if original is not None else self.old,
                                learned if learned is not None else self.learned,
                                profiler if profiler is not None else self.profiler,
                                trace if trace is not None else self.physical)

    def altered(self,editor):
        v=copy.deepcopy(self.physical)
        editor(v)
        v['receipt_sha256']=top1.digest({k:z for k,z in v.items() if k!='receipt_sha256'})
        return v

    def rejects(self,editor,message=None):
        v=self.altered(editor)
        with self.assertRaisesRegex(ValueError,message or '.'):
            self.review_trace(v)

    def test_complete_source_bound_true_torch_training_and_full_census(self):
        p=self.physical;self.assertEqual((p['physical_encoder_calls_in_this_job'],len(p['measured_trials'])),(224,32))
        self.assertEqual(p['measured_rounds'],8)
        self.assertEqual(len(p['warmup_trials']),4)
        self.assertEqual(self.score['observations'],32)
        self.assertEqual(self.score['warmup_training_runs_paid'],4)
        self.assertEqual(self.score['physical_training_forward_cases_from_complete_census'],8*3*3840)

    def test_equal_four_positions_by_permutation_not_sequential_bias(self):
        self.assertEqual(self.physical['crossover_orders'],prod.order_for_rounds(20261015,8))
        self.assertEqual(self.physical['crossover_orders'],audit.order(20261015,8))
        for arm in prod.ARMS:
            self.assertEqual(self.score['per_arm'][arm]['balanced_position_histogram'],[2]*4)

    def test_original_model_unchanged_when_224_additional_encodings_and_trials_replayed(self):
        self.assertEqual(self.physical['model_weights_sha256'],self.learned['original_model_weights_sha256'])
        self.assertFalse(self.physical['pretrained_model_loaded_in_this_job'])
        self.assertEqual(self.physical['model_load_ms_observed_by_backend'],None)
        self.assertEqual(self.physical['physical_encoder_calls_in_this_job'],224)

    def test_all_four_previous_weights_and_96_logits_replayed_every_trial(self):
        for row in self.physical['warmup_trials']+self.physical['measured_trials']:
            original=self.learned['compared_arms'][row['arm']]
            self.assertEqual(row['original_final_weights_sha256'],original['final_weights_sha256'])
            self.assertLessEqual(row['original_heldout_logits_max_abs'],prod.TOL)
            self.assertEqual(row['training_selected_expert_rows'],original['train_physical_selected_expert_rows'])

    def test_timing_is_observed_not_profiler_wrapped_or_host_attested(self):
        self.assertTrue(self.physical['operator_profiler_disabled_for_timing'])
        self.assertTrue(self.physical['time_traces_are_not_independently_attested'])
        self.assertFalse(self.score['complete_backward_flops_verified'])
        self.assertFalse(self.score['equal_full_lifecycle_compute_verified'])
        self.assertFalse(self.score['signed_target_hardware_timings_verified'])
        self.assertFalse(self.physical['p99_requests_independently_sampled'])

    def test_no_reject_valid_negative_cost_advantages_or_slow_outliers(self):
        for arm in prod.ARMS:
            row=self.score['per_arm'][arm]
            self.assertGreater(row['median_paired_full_head_cpu_ratio_vs_single'],0)
            self.assertLessEqual(row['observed_wall_min_ns'],row['observed_wall_max_ns'])
            self.assertFalse(row['slowest_case_excluded'])
        self.assertEqual(self.score['per_arm']['single_active']['median_paired_full_head_cpu_ratio_vs_single'],1)

    def test_count_all_warmup_training_lifecycle_even_when_excluded_from_steady_state_median(self):
        warm=self.physical['warmup_trials']
        self.assertGreater(sum(v['measured_total_cpu_ns'] for v in warm),0)
        self.assertEqual(sum(r['measured_total_cpu_ns'] for r in warm+self.physical['measured_trials']),
                         self.score['complete_cpu_sum_ns_including_warmup'])

    def test_16_24_32_and_bad_rounds_preregistered(self):
        self.assertEqual(len(prod.order_for_rounds(27,16)),16)
        self.assertEqual(len(prod.order_for_rounds(27,24)),24)
        self.assertEqual(len(prod.order_for_rounds(27,32)),32)
        for rounds in (0,1,2,4,7,9,10,12,33,False):
            with self.assertRaises(ValueError):prod.order_for_rounds(27,rounds)
        for seed in (-1,0,True,2**31):
            with self.assertRaises(ValueError):prod.order_for_rounds(seed,8)

    def test_source_changed_train_label_fails_before_timing(self):
        bad=copy.deepcopy(self.train)
        bad['rows'][0]['label']^=1
        with patch.object(p1,'PANEL_SHA',self.panel_sha):
            with self.assertRaises(ValueError):
                prod.execute(bad,self.blind,self.backend,self.old,self.learned,rounds=8)

    def test_source_changed_original_model_identity_fails_before_timing(self):
        prior_model=copy.deepcopy(self.old)
        prior_model['frozen_model_weights_sha256']='e'*64
        prior_model['report_sha256']=top1.digest({k:v for k,v in prior_model.items() if k!='report_sha256'})
        with patch.object(p1,'PANEL_SHA',self.panel_sha):
            with self.assertRaises(ValueError):
                prod.execute(self.train,self.blind,self.backend,prior_model,self.learned,rounds=8)

    def test_real_pretend_rejected_no_mock_model_weight_promotion(self):
        with patch.object(p1,'PANEL_SHA',self.panel_sha):
            with self.assertRaises(ValueError):
                prod.execute(self.train,self.blind,self.backend,self.old,self.learned,real=True,rounds=8)

    def test_blind_test_labels_not_allowed_in_prelabel_cost_execution(self):
        bad=copy.deepcopy(self.blind);bad['rows'][0]['label']=1
        with patch.object(p1,'PANEL_SHA',self.panel_sha):
            with self.assertRaises(ValueError):
                prod.execute(self.train,bad,self.backend,self.old,self.learned,rounds=8)

    def test_rehashed_optimistic_model_promotion_fails(self):
        self.rejects(lambda d:d.update(production_promotion_permitted=True),'false')
        self.rejects(lambda d:d.update(model_winner_selected=True),'false')

    def test_rehashed_total_flop_or_e2e_certificate_fails(self):
        self.rejects(lambda d:d.update(exact_total_flops_matched=True),'false')
        self.rejects(lambda d:d.update(target_worker_end_to_end_certified=True),'false')
        self.rejects(lambda d:d.update(p99_requests_independently_sampled=True),'false')

    def test_rehashed_profiler_timing_falsehood_fails(self):
        self.rejects(lambda d:d.update(operator_profiler_disabled_for_timing=False))
        self.rejects(lambda d:d.update(time_traces_are_not_independently_attested=False))

    def test_missing_one_round_or_cherrypicked_slowest_case_fails(self):
        self.rejects(lambda d:d['measured_trials'].pop())
        self.rejects(lambda d:d['measured_trials'].pop(15))

    def test_swapped_positions_and_rehashed_false_balance_fails(self):
        self.rejects(lambda d:d['measured_trials'][3].update(position=0),'order')
        self.rejects(lambda d:d['crossover_orders'].reverse(),'rotations')

    def test_rehashed_new_seed_wrong_design_fails(self):
        self.rejects(lambda d:d.update(crossover_seed=27),'rotations')
        self.rejects(lambda d:d.update(measured_rounds=9),'round')

    def test_wrong_warmup_inventory_and_free_replayed_training_fails(self):
        self.rejects(lambda d:d['warmup_trials'].pop())
        self.rejects(lambda d:d['warmup_trials'][0].update(arm='fixed_top1'))
        self.rejects(lambda d:d.update(warmup_runs_counted_as_work=False))

    def test_rehashed_nonpositive_cpu_wall_or_smaller_than_inner_stages_fails(self):
        self.rejects(lambda d:d['measured_trials'][0].update(measured_total_wall_ns=0))
        self.rejects(lambda d:d['measured_trials'][1].update(measured_total_cpu_ns=1))
        self.rejects(lambda d:d['measured_trials'][2].update(
                     measured_total_wall_ns=d['measured_trials'][2]['internally_measured_train_wall_ns']))

    def test_rehashed_wrong_actual_gradient_updates_fails(self):
        self.rejects(lambda d:d['measured_trials'][0].update(train_updates=10))
        self.rejects(lambda d:d['measured_trials'][1].update(training_selected_expert_rows=[0,0]))

    def test_rehashed_split_migration_cannot_be_erased(self):
        self.rejects(lambda d:d['measured_trials'][3].update(migration_copied_fp32_bytes=4))
        self.rejects(lambda d:d['measured_trials'][3].update(split_parity_extra_forward_rows=12))

    def test_rehashed_original_source_heldout_inventory_cannot_change(self):
        self.rejects(lambda d:d.update(original_source_inventory=[]),'source')
        self.rejects(lambda d:d.update(source_panel_sha256='f'*64),'source')

    def test_rehashed_model_weight_or_first_retrospective_cost_refuses(self):
        self.rejects(lambda d:d.update(model_weights_sha256='f'*64),'model')
        self.rejects(lambda d:d.update(original_trained_top1_sha256='f'*64),'model')

    def test_no_extra_fields_no_untracked_saved_resources(self):
        self.rejects(lambda d:d.update(extra_costs_were_free=True),'schema')
        self.rejects(lambda d:d['measured_trials'][0].update(omitted_measurements=1))

    def test_missing_signed_external_model_source_fails_original_independent_review(self):
        obs=copy.deepcopy(self.profiler)
        obs['source_model_publisher_signed']=True
        obs['report_sha256']=top1.digest({k:v for k,v in obs.items() if k!='report_sha256'})
        with self.assertRaises(ValueError):self.review_trace(profiler=obs)

    def test_original_pretrained_fake_claim_rejected_even_with_new_receipt_hash(self):
        self.rejects(lambda d:d.update(pretrained_model_loaded_in_this_job=True),'source')

    def test_independent_score_opens_labels_after_all_original_predictors(self):
        wrong=copy.deepcopy(self.labels)
        wrong['rows'][0]['label']=1-wrong['rows'][0]['label']
        with self.assertRaises(ValueError):self.review_trace(labels=wrong)

    def test_predeclared_small_n_no_p99_or_independent_future_claim(self):
        self.assertTrue(self.score['retrospective_repeated_cpu_trials_not_independent_test_cases'])
        self.assertFalse(self.score['equal_full_lifecycle_compute_verified'])
        self.assertNotIn('p99_latency_ms',str(self.score))

    def test_some_cold_start_overhead_is_included_not_minus_hidden(self):
        self.assertGreater(self.score['complete_wall_sum_ns_including_warmup'],
                           sum(r['measured_total_wall_ns'] for r in self.physical['measured_trials']))

    def test_exclude_unsuccessful_original_profiler_as_unsupported_cost(self):
        other=copy.deepcopy(self.profiler)
        other['complete_backward_flops_verified']=True
        other['report_sha256']=top1.digest({k:v for k,v in other.items() if k!='report_sha256'})
        with self.assertRaises(ValueError):self.review_trace(profiler=other)


if __name__=='__main__':unittest.main()
