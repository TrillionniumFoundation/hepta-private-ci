"""Offline independent reviewer refusal + original raw meter parity contracts."""
from __future__ import annotations

from copy import deepcopy
import unittest

from e6_physical import bench
from e6_independent_review import ReviewError, audit


def cases():
    return [bench(n,2,1,False) for n in (64,256,1024,4096)]


class E6IndependentAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.control=cases()

    def test_four_fresh_physical_scales_recomputed_not_reported_only(self):
        x=audit(deepcopy(self.control))
        self.assertEqual(set(x['physical_cohorts']),{'64','256','1024','4096'})
        self.assertEqual(x['total_new_real_pretrained_encoder_forwards'],0)
        self.assertTrue(x['recomputed_raw_summary_statistics'])
        self.assertFalse(x['production_accepted'])

    def test_exclusive_identity_reuse_and_4096_heads(self):
        x=audit(self.control)
        self.assertEqual(x['physical_cohorts']['4096']['actual_head_forwards_per_trial'],4096)
        self.assertEqual(x['physical_cohorts']['4096']['synthetic_cached_calls'],2)
        self.assertEqual(x['physical_cohorts']['4096']['synthetic_nonreuse_calls'],4096)

    def test_missing_scale_rejected(self):
        with self.assertRaises(ReviewError):
            audit(self.control[:-1])

    def test_claim_pretrained_forward_rejected(self):
        x=deepcopy(self.control);x[0]['real_pretrained_forward_count']=1
        with self.assertRaises(ReviewError):audit(x)

    def test_claim_live_final_use_rejected(self):
        x=deepcopy(self.control);x[1]['qualified_final_use']=True
        with self.assertRaises(ReviewError):audit(x)

    def test_misreported_weight_bytes_rejected(self):
        x=deepcopy(self.control);x[2]['head_bank_trainable_weight_bytes']-=4
        with self.assertRaises(ReviewError):audit(x)

    def test_misreported_cached_forwards_rejected(self):
        x=deepcopy(self.control);x[3]['arms']['cached']['synthetic_encoder_invocations_per_trial']=1
        with self.assertRaises(ReviewError):audit(x)

    def test_changed_meter_samples_rejected(self):
        x=deepcopy(self.control);x[0]['arms']['cached']['observed_batch_wall_ns'][0]+=100
        with self.assertRaises(ReviewError):audit(x)

    def test_changed_trial_count_rejected(self):
        x=deepcopy(self.control);x[0]['trials']=3
        with self.assertRaises(ReviewError):audit(x)

    def test_lifted_prod_flag_denied(self):
        x=deepcopy(self.control);x[3]['production_accepted']=True
        with self.assertRaises(ReviewError):audit(x)


if __name__=='__main__':
    unittest.main()
