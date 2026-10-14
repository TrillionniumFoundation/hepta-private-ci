"""Physical PyTorch sparse-SGD mechanism tests. Features and targets are synthetic."""
import unittest
import torch
from e5_sparse_packed_sgd import Invalid, run, selected_indices, packed_bank, frozen_hash

class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.p, cls.plogits, cls.weights = run(64,8,'packed',steps=3,return_validation=True)
        cls.m, cls.mlogits, cls.modules = run(64,8,'modules',steps=3,return_validation=True)

    def test_initial_parameters_match(self):
        self.assertEqual(self.p['initial_active_weights_sha256'],self.m['initial_active_weights_sha256'])
    def test_sgd_numerically_matches(self):
        self.assertTrue(torch.allclose(self.plogits,self.mlogits,atol=1e-5,rtol=1e-5))
        for key in self.weights:
            self.assertTrue(torch.allclose(self.weights[key],self.modules[key],atol=1e-5,rtol=1e-5),key)
    def test_logits_shape_and_real_update(self):
        self.assertEqual(tuple(self.plogits.shape),(8,8))
        self.assertNotEqual(self.p['initial_active_weights_sha256'],self.p['final_active_weights_sha256'])
    def test_dormant_cells_retained(self):
        self.assertTrue(self.p['dormant_weights_unchanged'])
        self.assertTrue(self.m['dormant_weights_unchanged'])
        self.assertEqual(self.m['dormant_bank_sha256_before'],self.m['dormant_bank_sha256_after'])
        self.assertEqual(self.p['dormant_bank_sha256_before'],self.p['dormant_bank_sha256_after'])
    def test_sparse_indices_not_just_prefix(self):
        idx=selected_indices(torch,64,8,20261014).tolist()
        self.assertNotEqual(idx,list(range(8)))
    def test_no_encoder_training(self):
        self.assertFalse(self.p['pretrained_encoder_executed'])
        self.assertFalse(self.p['production_promotion_permitted'])
    def test_complete_resident_head_count(self):
        self.assertEqual(self.p['observed_resident_head_parameters'],64*9744)
    def test_identity_for_dormant_subset_changes_only_when_weights_do(self):
        bank=packed_bank(torch,64,20261014)
        active=selected_indices(torch,64,8,20261014).tolist()
        before=frozen_hash(bank,64,active)
        with torch.no_grad(): bank['output.bias'][0,0] += 1
        if 0 not in active:
            self.assertNotEqual(before,frozen_hash(bank,64,active))
    def test_invalid_scale(self):
        with self.assertRaises(Invalid):run(100,8,'packed')
    def test_invalid_mode(self):
        with self.assertRaises(Invalid):run(64,8,'strange')
    def test_invalid_step(self):
        with self.assertRaises(Invalid):run(64,8,'packed',steps=0)
    def test_loss_real_and_finite(self):
        self.assertEqual(len(self.p['training_loss_by_step_sum']),3)
        self.assertTrue(all(x>0 and x<100 for x in self.p['training_loss_by_step_sum']))

if __name__=='__main__':unittest.main()
