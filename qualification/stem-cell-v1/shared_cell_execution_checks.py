"""Shared basis arithmetic; synthetic tensors are not pretrained evidence."""
from copy import deepcopy
import unittest

import torch

from development_tensors import BasisCellHeads, parameter_digest
from shared_cell_execution import forward_shared


class SharedCellExecutionTests(unittest.TestCase):
    def setUp(self):
        self.bank = BasisCellHeads(16, 4, 8, ("a", "b", "c", "d"), seed=7)
        g = torch.Generator().manual_seed(13)
        with torch.no_grad():
            self.bank.coefficients.copy_(torch.randn(4, 8, generator=g))
            self.bank.gates.copy_(torch.randn(4, 9, generator=g))
        self.features = torch.randn(3, 16, generator=g)
        self.fids = torch.tensor([2, 0, 1, 2, 1, 0], dtype=torch.long)
        self.cids = torch.tensor([3, 0, 1, 2, 0, 1], dtype=torch.long)

    def test_matches_ordinary_batch_and_preserves_order(self):
        before = parameter_digest(self.bank)
        out = forward_shared(self.bank, self.features, self.fids, self.cids)
        reference = self.bank(self.features[self.fids], self.cids)
        torch.testing.assert_close(out, reference, atol=1e-5, rtol=1e-5)
        self.assertTrue(torch.equal(out.argmax(1), reference.argmax(1)))
        self.assertEqual(parameter_digest(self.bank), before)

    def test_gradient_parity_including_duplicate_feature_accumulation(self):
        a, b = deepcopy(self.bank).double(), deepcopy(self.bank).double()
        a.requires_grad_(True); b.requires_grad_(True)
        x = self.features.double().requires_grad_()
        y = self.features.double().requires_grad_()
        forward_shared(a, x, self.fids, self.cids).square().sum().backward()
        b(y[self.fids], self.cids).square().sum().backward()
        torch.testing.assert_close(x.grad, y.grad, atol=1e-9, rtol=1e-9)
        for pa, pb in zip(a.parameters(), b.parameters()):
            torch.testing.assert_close(pa.grad, pb.grad, atol=1e-9, rtol=1e-9)

    def test_exact_zero_delta_birth(self):
        with torch.no_grad():
            self.bank.coefficients.zero_()
        out = forward_shared(self.bank, self.features, self.fids, self.cids)
        torch.testing.assert_close(out, self.bank.base(self.features)[self.fids], atol=0, rtol=0)

    def test_bad_identity_indices_before_kernel(self):
        seen = []
        hook = self.bank.base.register_forward_pre_hook(lambda *_: seen.append(1))
        try:
            for ids in (self.cids.float(), torch.tensor([4]*6), torch.tensor([-1]*6), self.cids[:2]):
                with self.subTest(ids=ids), self.assertRaises(ValueError):
                    forward_shared(self.bank, self.features, self.fids, ids)
            self.assertEqual(seen, [])
        finally:
            hook.remove()

    def test_unused_or_out_of_range_features_rejected(self):
        for fids in (self.fids + 1, torch.tensor([-1]*6), torch.zeros(6, dtype=torch.long)):
            with self.subTest(fids=fids), self.assertRaises(ValueError):
                forward_shared(self.bank, self.features, fids, self.cids)

    def test_dormant_cell_refused(self):
        self.bank.awake = (True, True, True, False)
        with self.assertRaisesRegex(ValueError, "dormant"):
            forward_shared(self.bank, self.features, self.fids, self.cids)

    def test_scratch_admission_precedes_projection(self):
        seen = []
        hook = self.bank.base.register_forward_pre_hook(lambda *_: seen.append(1))
        try:
            with self.assertRaisesRegex(ValueError, "scratch"):
                forward_shared(self.bank, self.features, self.fids, self.cids, maximum_scratch_elements=1)
            self.assertEqual(seen, [])
        finally:
            hook.remove()

    def test_input_and_computed_nonfinite_refused(self):
        x = self.features.clone(); x[0, 0] = torch.nan
        with self.assertRaises(ValueError):
            forward_shared(self.bank, x, self.fids, self.cids)
        with torch.no_grad():
            self.bank.basis.fill_(torch.finfo(torch.float32).max)
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            forward_shared(self.bank, self.features.abs() + 1, self.fids, self.cids)

    def test_no_persistent_feature_cache_or_stale_parameters(self):
        before = forward_shared(self.bank, self.features, self.fids, self.cids)
        with torch.no_grad():
            self.bank.coefficients[0].add_(2)
        after = forward_shared(self.bank, self.features, self.fids, self.cids)
        reference = self.bank(self.features[self.fids], self.cids)
        self.assertFalse(torch.equal(before, after))
        torch.testing.assert_close(after, reference, atol=1e-5, rtol=1e-5)

    def test_all_cells_have_independent_coefficients_at_4096_scale(self):
        bank = BasisCellHeads(8, 2, 4, tuple(f"c{i}" for i in range(4096)), seed=3)
        with torch.no_grad():
            bank.coefficients[:, 0] = torch.arange(4096) / 4096
        fids = torch.zeros(4096, dtype=torch.long)
        cids = torch.arange(4096)
        x = torch.ones(1, 8)
        out = forward_shared(bank, x, fids, cids)
        torch.testing.assert_close(out, bank(x[fids], cids), atol=1e-5, rtol=1e-5)
        self.assertEqual(len(torch.unique(out, dim=0)), 4096)



if __name__ == "__main__":
    unittest.main()
