"""Synthetic single-row CPU mask contracts, never a physical model receipt."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import torch
import replacement_arctic_unpadded_mask as shim


class GteModel(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.config = SimpleNamespace(use_memory_efficient_attention=False,
                                      unpad_inputs=False)
        self.weight = torch.nn.Parameter(torch.tensor([1.0], dtype=torch.float32))


class ArcticMaskTests(unittest.TestCase):
    @patch("replacement_arctic_unpadded_mask.metadata.version", return_value="5.20.2")
    def test_bounded_unpadded_identity_and_negative_masks(self, unused_version):
        model = GteModel()
        before = model.weight.detach().clone()
        receipt = shim.install_arctic_unpadded_mask(model)
        self.assertEqual(receipt["scope"], shim.SCOPE)
        self.assertFalse(receipt["production_qualified"])
        self.assertTrue(torch.equal(before, model.weight))
        for n in (1, 7, 192):
            observed = model.get_extended_attention_mask(torch.ones(1, n, dtype=torch.long),
                                                          torch.Size((1, n)))
            self.assertEqual(tuple(observed.shape), (1, 1, 1, n))
            self.assertEqual(observed.dtype, torch.float32)
            self.assertEqual(torch.count_nonzero(observed).item(), 0)
        invalid = [
            (torch.tensor([[1, 0]], dtype=torch.long), (1, 2)),
            (torch.ones((2, 3), dtype=torch.long), (2, 3)),
            (torch.ones((1, 193), dtype=torch.long), (1, 193)),
            (torch.ones((1, 3), dtype=torch.float32), (1, 3)),
            (torch.ones((1, 3), dtype=torch.long), (1, 2)),
        ]
        for mask, shape in invalid:
            with self.subTest(shape=shape):
                with self.assertRaisesRegex(ValueError, "unpadded"):
                    model.get_extended_attention_mask(mask, shape)
        self.assertTrue(torch.equal(before, model.weight))

    @patch("replacement_arctic_unpadded_mask.metadata.version", return_value="5.20.2")
    def test_fail_closed_for_other_runtime(self, unused_version):
        model = GteModel()
        model.config.unpad_inputs = True
        with self.assertRaisesRegex(ValueError, "unexpected"):
            shim.install_arctic_unpadded_mask(model)
        model.config.unpad_inputs = False
        model.get_extended_attention_mask = lambda *_: None
        with self.assertRaisesRegex(ValueError, "unexpected"):
            shim.install_arctic_unpadded_mask(model)

    @patch("replacement_arctic_unpadded_mask.metadata.version", return_value="5.20.3")
    def test_unpinned_transformers_refused(self, unused_version):
        with self.assertRaisesRegex(ValueError, "unexpected"):
            shim.install_arctic_unpadded_mask(GteModel())


if __name__ == "__main__":
    unittest.main()
