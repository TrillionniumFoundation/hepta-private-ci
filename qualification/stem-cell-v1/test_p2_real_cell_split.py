"""Numerical P2 equal-parameter Cell split controls; ONLY synthetic Stem mock."""
from __future__ import annotations

import copy
import hashlib
import unittest
from unittest.mock import patch

import torch

import p1_real_granite_cohort as p1
import p1_real_granite_review as p1review
import p2_real_cell_split as p2
import p2_real_cell_split_review as review
from test_p1_real_granite_cohort import FakePhysicalStem,setup_fixture


class P2EqualBudgetSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel,cls.train,cls.blind,cls.owner,cls.original_sha=setup_fixture()
        torch.manual_seed(7359)
        cls.backend=FakePhysicalStem()
        with patch.object(p1,'PANEL_SHA',cls.original_sha),patch.object(p1review,'PANEL_SHA',cls.original_sha):
            cls.record=p2.execute(cls.train,cls.blind,cls.backend,seed=7347)
            cls.scored=review.review(cls.panel,cls.train,cls.blind,cls.owner,cls.record)

    def score(self,r,*,owner=None,blind=None,panel=None,train=None):
        with patch.object(p1review,'PANEL_SHA',self.original_sha):
            return review.review(panel or self.panel,train or self.train,
                  blind or self.blind,owner or self.owner,r)

    def test_all_four_arms_numeric_replayed(self):
        self.assertTrue(self.scored['all_four_model_arms_replayed'])
        self.assertEqual(set(self.scored['results']),set(p2.ARMS))
        self.assertEqual(self.scored['source_group_effective_independent_n'],0)
        self.assertFalse(self.scored['eligible_model_selection'])

    def test_exact_provenance_and_224_actual_encoder_calls(self):
        self.assertEqual(self.backend.calls,224)
        self.assertEqual(self.record['original_source_model_api_calls'],224)
        self.assertEqual(len(self.record['source_heldout_cases']),96)
        self.assertEqual(len(self.record['source_features_q24']),96)
        self.assertFalse(self.record['frozen_pretrained_source_execution_claimed'])
        self.assertFalse(self.record['physical_4096_active_pretrained_split_executed'])

    def test_parameter_capacity_initialization_and_update_exposure_matched(self):
        rows=self.record['compared_arms']
        self.assertEqual({r['parameter_count'] for r in rows.values()},{14868})
        self.assertEqual({r['initial_weights_sha256'] for a,r in rows.items()
                         if a!='wide_single_equal_parameter'},
                         {rows['frozen_no_change']['initial_weights_sha256']})
        self.assertEqual(rows['frozen_no_change']['optimization_steps'],0)
        self.assertEqual({r['training_example_exposures'] for a,r in rows.items()
                          if a!='frozen_no_change'},{3840})

    def test_true_wide_single_head_exact_equal_14868_parameters(self):
        wide=self.record['compared_arms']['wide_single_equal_parameter']
        self.assertEqual(wide['private_head_parameter_count'],14868)
        self.assertEqual(set(wide['weights']),set(review.WIDE_SHAPES))
        self.assertEqual(wide['optimization_steps'],40)
        self.assertFalse(wide['split_proposed'])
        self.assertIn('wide_single_equal_parameter',self.scored['results'])

    def test_tampered_true_wide_head_logit_rejected_by_independent_numpy(self):
        r=copy.deepcopy(self.record)
        r['compared_arms']['wide_single_equal_parameter']['logits'][0][0]+=0.3
        r['report_sha256']=p2.digest({k:v for k,v in r.items() if k!='report_sha256'})
        with self.assertRaisesRegex(ValueError,'NumPy cannot reproduce'):
            self.score(r)

    def test_train_only_adaptive_rule_not_holdout_labels(self):
        row=self.record['compared_arms']['adaptive_train_only']
        self.assertEqual(row['split_proposed'],row['train_only_split_excess_brier']>.03)
        self.assertEqual(row['parent_to_child_max_abs_error'],0)
        self.assertFalse(row['training_uses_test_labels'])
        self.assertFalse(row['heldout_original_labels_opened'])

    def test_negative_null_results_are_retained(self):
        self.assertEqual(set(self.scored['paired_to_unrouted']),set(p2.ARMS[1:]))
        self.assertFalse(self.scored['independent_future_task_utility_established'])
        for row in self.scored['results'].values():
            self.assertEqual((row['calibration']['n'],row['test']['n']),(32,64))
            self.assertLessEqual(row['sealed_logits_max_abs_replay_error'],4e-5)

    def test_original_panel_label_change_fails_even_if_receipt_rehashed(self):
        label=copy.deepcopy(self.owner)
        label['rows'][0]['label']=1-label['rows'][0]['label']
        label['seal_id']=p2.digest({k:v for k,v in label.items() if k!='seal_id'})
        with self.assertRaises(ValueError):self.score(self.record,owner=label)

    def test_blind_material_cannot_carry_eval_labels(self):
        tampered=copy.deepcopy(self.blind)
        tampered['rows'][0]['label']=1
        with self.assertRaises(ValueError):self.score(self.record,blind=tampered)

    def test_wrong_stem_large_pretrained_flag_refused(self):
        r=copy.deepcopy(self.record)
        r['frozen_pretrained_source_execution_claimed']=True
        r['report_sha256']=p2.digest({k:v for k,v in r.items() if k!='report_sha256'})
        with self.assertRaisesRegex(ValueError,'fake public pretrained'):
            self.score(r)

    def test_bad_future_or_capacity_claim_rejected(self):
        for field in ('ndu_system2_superiority_established',
                      'general_reasoning_equivalence_10t_100t_established',
                      'physical_4096_active_pretrained_split_executed',
                      'reader_sufficiency_established','selection_authorized'):
            r=copy.deepcopy(self.record);r[field]=True
            r['report_sha256']=p2.digest({k:v for k,v in r.items() if k!='report_sha256'})
            with self.assertRaisesRegex(ValueError,'unsupported'):
                self.score(r)

    def test_invented_critical_field_rejected(self):
        r=copy.deepcopy(self.record);r['statistical_split_winner']=True
        r['report_sha256']=p2.digest({k:v for k,v in r.items() if k!='report_sha256'})
        with self.assertRaisesRegex(ValueError,'extra or missing'):
            self.score(r)

    def test_mutated_heldout_feature_rejected_by_independent_math(self):
        r=copy.deepcopy(self.record)
        k=next(iter(r['source_features_q24']))
        r['source_features_q24'][k][0]+=123_456
        r['report_sha256']=p2.digest({k:v for k,v in r.items() if k!='report_sha256'})
        with self.assertRaisesRegex(ValueError,'NumPy cannot reproduce'):
            self.score(r)

    def test_changed_logits_even_if_resealed_rejected(self):
        r=copy.deepcopy(self.record)
        r['compared_arms']['fixed_two_cell']['logits'][0][1]+=0.4
        r['report_sha256']=p2.digest({k:v for k,v in r.items() if k!='report_sha256'})
        with self.assertRaisesRegex(ValueError,'NumPy cannot reproduce'):
            self.score(r)

    def test_changed_weight_bytes_and_resealed_rejected(self):
        r=copy.deepcopy(self.record)
        packed=r['compared_arms']['fixed_two_cell']['weights']['out']['bytes_le_hex']
        r['compared_arms']['fixed_two_cell']['weights']['out']['bytes_le_hex']='00000000'+packed[8:]
        r['report_sha256']=p2.digest({k:v for k,v in r.items() if k!='report_sha256'})
        with self.assertRaisesRegex(ValueError,'trained FP32 weight digest'):
            self.score(r)

    def test_incorrect_initial_seed_matching_refused(self):
        r=copy.deepcopy(self.record)
        r['compared_arms']['adaptive_train_only']['initial_weights_sha256']='f'*64
        r['report_sha256']=p2.digest({k:v for k,v in r.items() if k!='report_sha256'})
        with self.assertRaisesRegex(ValueError,'initial Head weights differ'):
            self.score(r)

    def test_false_optimizer_steps_and_exposure_rejected(self):
        for field,value in [('optimization_steps',41),('training_example_exposures',128)]:
            r=copy.deepcopy(self.record);r['compared_arms']['fixed_two_cell'][field]=value
            r['report_sha256']=p2.digest({k:v for k,v in r.items() if k!='report_sha256'})
            with self.assertRaises(ValueError):self.score(r)

    def test_frozen_original_state_changed_refused(self):
        r=copy.deepcopy(self.record)
        r['compared_arms']['frozen_no_change']['initial_weights_sha256']='e'*64
        r['report_sha256']=p2.digest({k:v for k,v in r.items() if k!='report_sha256'})
        with self.assertRaises(ValueError):self.score(r)

    def test_retrofitted_split_selection_denied(self):
        r=copy.deepcopy(self.record)
        arm=r['compared_arms']['adaptive_train_only']
        arm['split_proposed']=not arm['split_proposed']
        r['report_sha256']=p2.digest({k:v for k,v in r.items() if k!='report_sha256'})
        with self.assertRaises(ValueError):self.score(r)

    def test_wrong_source_denominator_refused(self):
        r=copy.deepcopy(self.record)
        r['source_heldout_cases'].pop()
        r['report_sha256']=p2.digest({k:v for k,v in r.items() if k!='report_sha256'})
        with self.assertRaisesRegex(ValueError,'source/answer identity'):
            self.score(r)

    def test_wrong_original_model_identity_refused(self):
        r=copy.deepcopy(self.record);r['model_revision']='bad'
        r['report_sha256']=p2.digest({k:v for k,v in r.items() if k!='report_sha256'})
        with self.assertRaises(ValueError):self.score(r)

    def test_unfrozen_backend_refuses_training(self):
        backend=FakePhysicalStem();backend.model.train()
        with patch.object(p1,'PANEL_SHA',self.original_sha):
            with self.assertRaisesRegex(ValueError,'frozen local PyTorch'):
                p2.execute(self.train,self.blind,backend)

    def test_fake_can_never_be_pinned_real_pretrained(self):
        backend=FakePhysicalStem()
        with patch.object(p1,'PANEL_SHA',self.original_sha):
            with self.assertRaisesRegex(ValueError,'real pinned 97M'):
                p2.execute(self.train,self.blind,backend,weight_origin='pinned_public_research')

    def test_all_model_weights_remain_unmodified(self):
        before=p1.backend_digest(self.backend)
        self.assertEqual(before[1],384*384+384)
        self.assertEqual(before[0],self.record['frozen_model_weights_sha256'])

if __name__=='__main__':unittest.main()
