"""Actually execute original P2 postfit model weights and strict independent audit."""
from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

import numpy as np
import torch

import p1_real_granite_cohort as p1
import p1_real_granite_review as p1review
import p2_real_cell_split as p2
import p2_real_cell_split_review as p2review
from test_p1_real_granite_cohort import FakePhysicalStem,setup_fixture
import p2_postfit_sparse_top1 as sparse
import p2_postfit_sparse_review as reviewer


class P2PostfitPhysicalTop1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original,cls.train,cls.blind,cls.labels,cls.source_sha=setup_fixture()
        cls.backend=FakePhysicalStem()
        with patch.object(p1,'PANEL_SHA',cls.source_sha):
            cls.p2_record=p2.execute(cls.train,cls.blind,cls.backend,seed=7347)
        cls.out=sparse.run(cls.p2_record,repetitions=20,warmups=2)
        with patch.object(p1review,'PANEL_SHA',cls.source_sha):
            cls.checked=reviewer.audit(cls.original,cls.train,cls.blind,cls.labels,
                                       cls.p2_record,cls.out)

    def audit(self,report):
        with patch.object(p1review,'PANEL_SHA',self.source_sha):
            return reviewer.audit(self.original,self.train,self.blind,self.labels,
                                  self.p2_record,report)

    @staticmethod
    def seal(report):
        report['report_sha256']=sparse.sha({k:v for k,v in report.items() if k!='report_sha256'})
        return report

    def reject(self,change,reason=None):
        r=copy.deepcopy(self.out)
        change(r)
        self.seal(r)
        with self.assertRaisesRegex(ValueError, reason if reason else '.*'):
            self.audit(r)

    def test_real_two_expert_torch_execution_fewer_rows(self):
        for k in ('fixed_two_cell','adaptive_train_only'):
            row=self.out['arms'][k]
            self.assertEqual(row['registered_dense_head_rows'],192)
            self.assertEqual(row['physical_active_head_rows'],96)
            self.assertEqual(row['declared_linear_mac_dense'],192*7424)
            self.assertEqual(row['declared_linear_mac_active'],96*7424)
            self.assertLessEqual(row['sparse_vs_dense_logits_max_abs'],4e-5)
            self.assertEqual(len(row['physical_selected_head_indices']),96)
            self.assertEqual(len(row['sparse_heldout_logits']),96)

    def test_true_wide_single_same_mac_as_dense_dual(self):
        wide=self.out['arms']['wide_single_equal_parameter']
        self.assertEqual(wide['physical_active_head_rows'],96)
        self.assertEqual(wide['declared_linear_mac_active'],96*14848)
        self.assertEqual(wide['declared_linear_mac_dense'],96*14848)
        self.assertEqual(wide['physical_selected_head_indices'],[])

    def test_unchanged_unrouted_head_correctly_no_savings(self):
        for kind in ('frozen_no_change','unrouted_equal_parameter'):
            row=self.out['arms'][kind]
            self.assertEqual(row['physical_active_head_rows'],192)
            self.assertEqual(row['registered_dense_head_rows'],192)
            self.assertEqual(row['declared_linear_mac_active'],row['declared_linear_mac_dense'])
            self.assertEqual(row['physical_selected_head_indices'],[])

    def test_full_batch_timing_census_not_per_row_p99(self):
        for row in self.out['arms'].values():
            for name in ('dense_batch_wall_ns','active_batch_wall_ns',
                         'dense_batch_process_cpu_ns','active_batch_process_cpu_ns'):
                self.assertEqual(len(row[name]),20)
                self.assertTrue(all(type(v) is int and v>0 for v in row[name]))
        self.assertEqual(self.out['request_unit'],'96-row-full-batch')
        self.assertFalse(self.checked['cost_adjusted_full_lifecycle_win_established'])

    def test_original_weights_and_original_96_logits_preserved(self):
        self.assertEqual(self.out['original_p2_report_sha256'],self.p2_record['report_sha256'])
        self.assertTrue(self.checked['independently_replayed_original_p2'])
        self.assertTrue(self.checked['declared_linear_mac_not_full_flops'])
        for row in self.out['arms'].values():
            self.assertLessEqual(row['dense_vs_original_p2_logits_max_abs'],4e-5)

    def test_logits_recomputed_after_rehash_catches_forgeries(self):
        self.reject(lambda r:r['arms']['fixed_two_cell']['sparse_heldout_logits'][0].__setitem__(0,
                   r['arms']['fixed_two_cell']['sparse_heldout_logits'][0][0]+.1),
                   'NumPy cannot reproduce')

    def test_route_swapped_even_when_same_shape_rejected(self):
        self.reject(lambda r:r['arms']['fixed_two_cell']['physical_selected_head_indices'].reverse(),
                    'sparse Top-1 router')

    def test_wrong_row_counts_rejected(self):
        self.reject(lambda r:r['arms']['adaptive_train_only'].__setitem__('physical_active_head_rows',192),
                    'sparse Top-1 router')

    def test_cannot_claim_full_mac_parity(self):
        self.reject(lambda r:r.__setitem__('strict_equal_online_mac_across_arms',True),
                    'forbidden resource authority')

    def test_cannot_claim_signed_physical_latency(self):
        self.reject(lambda r:r.__setitem__('time_measurements_self_reported',False),
                    'forbidden resource authority')

    def test_wrong_head_weight_identity_rejected(self):
        self.reject(lambda r:r['arms']['wide_single_equal_parameter'].__setitem__('final_weights_sha256','1'*64),
                    'original trained parameter')

    def test_duplicate_timing_slot_rejected(self):
        self.reject(lambda r:r['arms']['wide_single_equal_parameter']['active_batch_wall_ns'].pop(),
                    'timing observations')

    def test_modified_mac_counter_rejected(self):
        self.reject(lambda r:r['arms']['fixed_two_cell'].__setitem__('declared_linear_mac_active',0),
                    'actual expert-row count')

    def test_same_replayed_quality_wins_and_losses_not_selected(self):
        self.assertFalse(self.checked['model_winner_selected'])
        self.assertFalse(self.checked['true_future_ood_utility_established'])
        self.assertEqual(set(self.checked['arms']),set(p2.ARMS))
        self.assertEqual(set(self.checked['original_quality_descriptive']),set(p2.ARMS))

    def test_wrong_source_sha_and_original_model_revision_rejected(self):
        self.reject(lambda r:r.__setitem__('original_frozen_model_sha256','0'*64),
                    'original model/cost')
        self.reject(lambda r:r.__setitem__('original_model_revision','injected'),
                    'original model/cost')

    def test_invented_result_key_rejected(self):
        self.reject(lambda r:r['arms']['fixed_two_cell'].__setitem__('estimated_speedup_proven',True),
                    'original trained parameter')

    def test_missing_arm_is_not_null_result(self):
        self.reject(lambda r:r['arms'].pop('adaptive_train_only'),
                    'all five')

    def test_original_unchanged_P2_score_replay_provenance(self):
        with patch.object(p1review,'PANEL_SHA',self.source_sha):
            direct=p2review.review(self.original,self.train,self.blind,self.labels,self.p2_record)
        self.assertEqual(direct['results'],self.checked['original_quality_descriptive'])

    def test_nonfinite_stored_logits_rejected_before_reporting(self):
        def change(r):r['arms']['unrouted_equal_parameter']['sparse_heldout_logits'][0][0]=float('nan')
        # The report-hash builder itself refuses nonfinite values rather than silently hashing NaN.
        r=copy.deepcopy(self.out)
        change(r)
        with self.assertRaises(ValueError):self.seal(r)

    def test_wrong_request_percentile_sample_type_rejected(self):
        self.reject(lambda r:r['arms']['frozen_no_change']['dense_batch_wall_ns'].__setitem__(0,False),
                    'timing observations')

    def test_adaptive_no_split_torch_really_one_head(self):
        model=sparse.restore(self.p2_record['compared_arms']['adaptive_train_only'])
        x=torch.randn(11,384,dtype=torch.float32)
        with torch.inference_mode():
            val,indices,count,batches=sparse.physical_sparse(model,x,0.,False)
            orig=model(x)[:,0,:]
        self.assertEqual(indices,[0]*11)
        self.assertEqual((count,batches),(11,1))
        self.assertLessEqual(float((val-orig).abs().max()),4e-5)

    def test_route_has_actual_both_active_experts_when_present(self):
        model=sparse.restore(self.p2_record['compared_arms']['fixed_two_cell'])
        x=torch.zeros(6,384,dtype=torch.float32)
        x[::2,0]=2.
        x[1::2,0]=-2.
        with torch.inference_mode():
            val,indices,count,batches=sparse.physical_sparse(model,x,0.,True)
            orig=p2.routing(model(x),x,'fixed_two_cell',split=True,threshold=0.)
        self.assertEqual((count,batches),(6,2))
        self.assertEqual(indices,[1,0,1,0,1,0])
        self.assertLessEqual(float((val-orig).abs().max()),4e-5)

if __name__=='__main__':unittest.main()
