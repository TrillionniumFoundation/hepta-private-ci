"""Model-free contract checks; actual pretrained forward is hosted-only."""
from __future__ import annotations
import unittest
from types import SimpleNamespace
from p0_mmbert_original_physical_probe_v15 import Invalid, checked_observation, SCHEMA


def fake():
    return SimpleNamespace(
      pretrained_weight_receipt={'actual_local_full_tied_embedding_checkpoint_verified':True,
                                 'complete_table_sha256':'a'*64,'authority':'DENY_ALL'},
      complete_weight_receipt={'all_serialized_pretrained_tensor_bytes_verified':True,
                               'whole_pretrained_state_sha256':'b'*64,
                               'source_tensor_count':137,'authority':'DENY_ALL'})

class PhysicalProofContractTests(unittest.TestCase):
    def test_complete_mock_structural_receipt_only(self):
        r=checked_observation(fake())
        self.assertEqual(r['source_tensor_count'],137)
        self.assertNotIn('production_accepted',r)
        self.assertNotIn('original_checkpoint_qualified',r)

    def test_false_preflight_denied(self):
        with self.assertRaises(Invalid):checked_observation(fake(),original_preflight=False)

    def test_false_tied_table_denied(self):
        x=fake();x.pretrained_weight_receipt['actual_local_full_tied_embedding_checkpoint_verified']=False
        with self.assertRaises(Invalid):checked_observation(x)

    def test_false_complete_tensor_check_denied(self):
        x=fake();x.complete_weight_receipt['all_serialized_pretrained_tensor_bytes_verified']=False
        with self.assertRaises(Invalid):checked_observation(x)

    def test_wrong_tensor_count_denied(self):
        x=fake();x.complete_weight_receipt['source_tensor_count']=136
        with self.assertRaises(Invalid):checked_observation(x)

    def test_empty_source_digest_denied(self):
        x=fake();x.complete_weight_receipt['whole_pretrained_state_sha256']=''
        with self.assertRaises(Invalid):checked_observation(x)

    def test_invalid_table_digest_denied(self):
        x=fake();x.pretrained_weight_receipt['complete_table_sha256']='c'*63+'/'
        with self.assertRaises(Invalid):checked_observation(x)

    def test_missing_original_report_denied(self):
        with self.assertRaises(Invalid):checked_observation(SimpleNamespace())

    def test_lifted_production_authority_denied(self):
        x=fake();x.complete_weight_receipt['authority']='PRODUCTION'
        with self.assertRaises(Invalid):checked_observation(x)

    def test_no_task_data_or_label_owner_access_in_source(self):
        from pathlib import Path
        p=Path(__file__).with_name('p0_mmbert_original_physical_probe_v15.py')
        t=p.read_text()
        self.assertIn('Original fixed pretrained mmBERT parameter-integrity probe.',t)
        self.assertNotIn('owner-only',t)
        self.assertNotIn('heldout_labels',t)

if __name__=='__main__':unittest.main()
