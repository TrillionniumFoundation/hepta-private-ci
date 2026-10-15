"""Actual CPU gradient, equal main-row work, and independent NumPy tamper tests.

Fake 147,840p Stem uses original source structure. No pretrained efficacy claim.
"""
from __future__ import annotations

import copy
import json
import unittest
from unittest.mock import patch

import torch
import p1_real_granite_cohort as p1
import p1_real_granite_review as p1check
import p2_real_cell_split as p2
import p2_train_sparse_equal_compute as target
import p2_train_sparse_equal_compute_review as independent
from test_p1_real_granite_cohort import FakePhysicalStem,setup_fixture


class TrainTrueTopOne(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original,cls.train,cls.blind,cls.labels,cls.panel_sha=setup_fixture()
        torch.manual_seed(7347)
        cls.stem=FakePhysicalStem()
        with patch.object(p1,'PANEL_SHA',cls.panel_sha):
            cls.old=p2.execute(cls.train,cls.blind,cls.stem,seed=7347)
            cls.report=target.execute(cls.train,cls.blind,cls.stem,seed=7347,parent_p2=cls.old)
        with patch.object(p1check,'PANEL_SHA',cls.panel_sha):
            cls.review=independent.review(cls.original,cls.train,cls.blind,cls.labels,cls.old,cls.report)

    def audit(self,record=None,*,prior=None,labels=None,blind=None,train=None,panel=None):
        with patch.object(p1check,'PANEL_SHA',self.panel_sha):
            return independent.review(panel or self.original,train or self.train,
                       blind or self.blind,labels or self.labels,
                       prior or self.old,record or self.report)

    def modified(self,path,val):
        r=copy.deepcopy(self.report)
        current=r
        for item in path[:-1]:current=current[item]
        current[path[-1]]=val
        r['report_sha256']=target.digest({k:v for k,v in r.items() if k!='report_sha256'})
        return r

    def test_full_new_four_arm_census_and_self_deny(self):
        self.assertEqual(set(self.report['compared_arms']),set(target.ARMS))
        self.assertEqual(set(self.review['new_arms']),set(target.ARMS))
        self.assertEqual(self.report['original_pretrained_encoder_forward_calls'],224)
        self.assertFalse(self.report['pretrained_weight_execution_claimed'])
        self.assertEqual(self.report['authority'],'DENY_ALL')
        self.assertFalse(self.review['production_promotion_permitted'])
        self.assertFalse(self.review['model_selection_authorized'])

    def test_frozen_original_same_q24_stem_and_head_bytes(self):
        self.assertEqual(self.report['source_features_q24'],self.old['source_features_q24'])
        self.assertEqual(self.report['original_model_weights_sha256'],self.old['frozen_model_weights_sha256'])
        self.assertEqual(self.report['original_frozen_two_head_initial_sha256'],
                         self.old['compared_arms']['frozen_no_change']['initial_weights_sha256'])
        self.assertEqual(self.report['compared_arms']['frozen_single']['train_updates'],0)
        self.assertEqual(self.report['compared_arms']['frozen_single']['heldout_selected_expert_rows'],[96,0])

    def test_three_learned_arms_match_actual_single_head_training_rows(self):
        r=self.report['compared_arms']
        self.assertEqual({r[name]['train_updates'] for name in target.MATCHED},{40})
        self.assertEqual({r[name]['train_examples_exposed'] for name in target.MATCHED},{3840})
        self.assertEqual({sum(r[name]['train_physical_selected_expert_rows']) for name in target.MATCHED},{3840})
        self.assertEqual({r[name]['train_forward_linear_mac'] for name in target.MATCHED},{3840*target.MAC_PER_EXPERT})
        self.assertEqual({r[name]['diagnostic_forward_linear_mac'] for name in target.MATCHED},{128*target.MAC_PER_EXPERT})
        self.assertEqual({r[name]['heldout_forward_linear_mac'] for name in target.MATCHED},{96*target.MAC_PER_EXPERT})

    def test_physical_sparse_forward_does_not_call_dense_two_head_forward(self):
        m=p2.TwoHeads(41)
        x=torch.randn(7,384,dtype=torch.float32)
        with patch.object(m,'forward',side_effect=AssertionError('unselected Head executed')):
            logits,count,calls=target.sparse_head(m,x,selected=torch.zeros(7,dtype=torch.long))
            self.assertEqual((count,calls),([7,0],1))
            loss=logits.square().mean();loss.backward()
        for param in m.parameters():
            self.assertTrue(param.grad is None or bool(torch.all(param.grad[1]==0)))

    def test_no_selected_expert_ever_doubles_forward_rows(self):
        m=p2.TwoHeads(41)
        x=torch.randn(5,384)
        logits,counts,calls=target.sparse_head(m,x,selected=torch.tensor([0,1,1,0,1]))
        self.assertEqual(logits.shape,(5,2))
        self.assertEqual((counts,calls),([2,3],2))
        self.assertEqual(sum(counts),5)

    def test_wrong_selector_dtype_duplicate_selection_invalid(self):
        m=p2.TwoHeads(41);x=torch.randn(2,384)
        with self.assertRaises(ValueError):target.sparse_head(m,x,selected=torch.tensor([0,2]))
        with self.assertRaises(ValueError):target.sparse_head(m,x,selected=torch.tensor([0.,1.]))
        with self.assertRaises(ValueError):target.sparse_head(m,x,selected=torch.zeros(4,dtype=torch.long))

    def test_single_active_dormant_tensor_byte_identical(self):
        a=self.report['compared_arms']['single_active']
        self.assertEqual(a['expert_one_before_sha256'],a['expert_one_after_sha256'])
        self.assertEqual(a['train_physical_selected_expert_rows'],[3840,0])
        self.assertFalse(a['split_proposed'])

    def test_fixed_top1_actually_updates_both_experts(self):
        a=self.report['compared_arms']['fixed_top1']
        self.assertTrue(a['split_proposed'])
        self.assertGreater(a['train_physical_selected_expert_rows'][0],0)
        self.assertGreater(a['train_physical_selected_expert_rows'][1],0)

    def test_adaptive_trigger_is_train_only_and_migration_fully_charged(self):
        a=self.report['compared_arms']['adaptive_top1']
        self.assertEqual(a['split_proposed'],a['train_only_split_excess_brier']>.03)
        if a['split_proposed']:
            self.assertEqual(a['migration_copied_fp32_bytes'],7434*4)
            self.assertEqual(a['split_parity_actual_head_forward_rows'],8)
            self.assertEqual(a['split_parity_actual_head_batch_calls'],2)
        else:
            self.assertEqual(a['migration_copied_fp32_bytes'],0)
        self.assertEqual(a['parent_clone_logits_max_abs'],0)

    def test_equal_main_training_mac_excludes_asymmetric_migration(self):
        self.assertFalse(self.report['exact_backward_flops_matched'])
        self.assertFalse(self.review['backward_flops_and_kernel_cost_matched'])
        self.assertTrue(self.report['actual_equal_forward_expert_rows_on_train'])
        self.assertTrue(self.review['primary_train_arms_equal_actual_forward_expert_rows'])

    def test_original_p2_still_independently_validated(self):
        self.assertEqual(set(self.review['original_p2_descriptive']),set(p2.ARMS))
        self.assertEqual(self.review['source_group_effective_independent_n'],0)
        self.assertFalse(self.review['old_new_split_is_temporal'])

    def test_immutable_new_report_digest_refused(self):
        r=copy.deepcopy(self.report);r['compared_arms']['single_active']['train_cpu_ns']+=1
        with self.assertRaisesRegex(ValueError,'sealed'):
            self.audit(r)

    def test_rehashed_prediction_swap_refused(self):
        r=copy.deepcopy(self.report)
        a=r['compared_arms']['fixed_top1'];a['heldout_logits'][0][0]+=0.3
        r['report_sha256']=target.digest({k:v for k,v in r.items() if k!='report_sha256'})
        with self.assertRaisesRegex(ValueError,'NumPy cannot reproduce'):
            self.audit(r)

    def test_rehashed_expert_weight_mutation_refused(self):
        r=copy.deepcopy(self.report)
        w=r['compared_arms']['single_active']['weights']['out']
        w['bytes_le_hex']='00000000'+w['bytes_le_hex'][8:]
        r['report_sha256']=target.digest({k:v for k,v in r.items() if k!='report_sha256'})
        with self.assertRaisesRegex(ValueError,'FP32 final tensor'):
            self.audit(r)

    def test_rehashed_cross_model_sha_refused(self):
        r=self.modified(['original_model_weights_sha256'],'f'*64)
        with self.assertRaisesRegex(ValueError,'different original model'):
            self.audit(r)

    def test_rehashed_cross_source_q24_refused(self):
        r=copy.deepcopy(self.report);key=self.blind['rows'][0]['case_id'];r['source_features_q24'][key][0]+=3000
        r['report_sha256']=target.digest({k:v for k,v in r.items() if k!='report_sha256'})
        with self.assertRaisesRegex(ValueError,'exact frozen source'):
            self.audit(r)

    def test_rehashed_router_indices_refused(self):
        r=copy.deepcopy(self.report);a=r['compared_arms']['fixed_top1'];a['heldout_selected_expert_ids'][1]^=1
        r['report_sha256']=target.digest({k:v for k,v in r.items() if k!='report_sha256'})
        with self.assertRaisesRegex(ValueError,'selected actual Head'):
            self.audit(r)

    def test_fake_training_steps_and_rows_refused(self):
        r=self.modified(['compared_arms','single_active','train_updates'],39)
        with self.assertRaises(ValueError):self.audit(r)
        r=self.modified(['compared_arms','single_active','train_physical_selected_expert_rows'],[3800,40])
        with self.assertRaises(ValueError):self.audit(r)

    def test_forged_equal_backward_cost_claim_refused(self):
        r=self.modified(['exact_backward_flops_matched'],True)
        with self.assertRaisesRegex(ValueError,'unsupported'):
            self.audit(r)

    def test_rehashed_unauthorized_model_selection_refused(self):
        r=self.modified(['production_model_selected'],True)
        with self.assertRaises(ValueError):self.audit(r)

    def test_rehashed_independent_future_claim_refused(self):
        r=self.modified(['independently_sourced_future_tasks_verified'],True)
        with self.assertRaises(ValueError):self.audit(r)

    def test_rehashed_false_pretrained_profile_refused(self):
        r=self.modified(['pretrained_weight_execution_claimed'],True)
        with self.assertRaises(ValueError):self.audit(r)

    def test_rehashed_forged_migration_cost_refused(self):
        a=self.report['compared_arms']['adaptive_top1']
        r=self.modified(['compared_arms','adaptive_top1','migration_copied_fp32_bytes'],
                        a['migration_copied_fp32_bytes']+4096)
        with self.assertRaisesRegex(ValueError,'unaccounted trained Cell'):
            self.audit(r)

    def test_rehashed_missing_duplicate_or_added_arm_refused(self):
        r=copy.deepcopy(self.report);r['compared_arms'].pop('single_active')
        r['report_sha256']=target.digest({k:v for k,v in r.items() if k!='report_sha256'})
        with self.assertRaises(ValueError):self.audit(r)
        r=self.modified(['spurious_scientific_winner'],True)
        with self.assertRaisesRegex(ValueError,'critical evidence'):
            self.audit(r)

    def test_changed_human_gold_refused_even_if_resealed(self):
        labels=copy.deepcopy(self.labels)
        labels['rows'][0]['label']=1-labels['rows'][0]['label']
        labels['seal_id']=target.digest({k:v for k,v in labels.items() if k!='seal_id'})
        with self.assertRaises(ValueError):self.audit(labels=labels)

    def test_swapped_genuine_heldout_source_refused(self):
        r=copy.deepcopy(self.report)
        r['source_heldout_cases'][0],r['source_heldout_cases'][1]=r['source_heldout_cases'][1],r['source_heldout_cases'][0]
        r['report_sha256']=target.digest({k:v for k,v in r.items() if k!='report_sha256'})
        with self.assertRaisesRegex(ValueError,'not exact frozen source'):
            self.audit(r)

    def test_prior_unverified_head_does_not_pass_original_p2_review(self):
        bad=copy.deepcopy(self.old)
        bad['compared_arms']['wide_single_equal_parameter']['logits'][0][0]+=1
        bad['report_sha256']=target.digest({k:v for k,v in bad.items() if k!='report_sha256'})
        with self.assertRaises(ValueError):self.audit(prior=bad)

    def test_test_labels_never_pass_into_training(self):
        bad=copy.deepcopy(self.blind)
        bad['rows'][0]['label']=1
        with patch.object(p1,'PANEL_SHA',self.panel_sha):
            with self.assertRaises(ValueError):
                target.execute(self.train,bad,self.stem,parent_p2=self.old)

    def test_model_snapshot_mismatch_blocks_training(self):
        altered=copy.deepcopy(self.old)
        altered['frozen_model_weights_sha256']='f'*64
        altered['report_sha256']=target.digest({k:v for k,v in altered.items() if k!='report_sha256'})
        with patch.object(p1,'PANEL_SHA',self.panel_sha):
            with self.assertRaises(ValueError):target.execute(self.train,self.blind,self.stem,parent_p2=altered)

    def test_mock_cannot_claim_actual_97m(self):
        with patch.object(p1,'PANEL_SHA',self.panel_sha):
            with self.assertRaisesRegex(ValueError,'actual original pinned Granite97'):
                target.execute(self.train,self.blind,self.stem,parent_p2=self.old,weight_origin='pinned_public_research')

    def test_migration_parity_not_counted_as_free(self):
        arm=self.report['compared_arms']['adaptive_top1']
        if arm['split_proposed']:
            r=self.modified(['compared_arms','adaptive_top1','split_parity_actual_head_forward_rows'],0)
            with self.assertRaises(ValueError):self.audit(r)

    def test_mixed_positive_and_negative_gains_not_filtered(self):
        observed=self.review['paired_against_single_active']
        self.assertEqual(set(observed),{
            'fixed_top1__vs__single_active__calibration',
            'fixed_top1__vs__single_active__test',
            'adaptive_top1__vs__single_active__calibration',
            'adaptive_top1__vs__single_active__test'})
        for v in observed.values():
            self.assertEqual(set(v),{'recovered','lost','difference_accuracy'})

if __name__=='__main__':unittest.main()
