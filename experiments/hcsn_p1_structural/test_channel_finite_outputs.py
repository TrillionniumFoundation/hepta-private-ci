"""Tiny CPU-f64 output-domain regression; no model or training."""
import math
import unittest

import torch

from .dual_channel_structural_gate import Refusal, channels


class ChannelOutputBoundaryTests(unittest.TestCase):
    def test_underflowed_ratio_cannot_return_nonfinite_margin(self):
        value = torch.tensor(math.ulp(0.0), dtype=torch.float64)
        scale = torch.tensor(1e7, dtype=torch.float64)
        self.assertTrue(torch.isfinite(value).item())
        self.assertTrue(torch.isfinite(scale).item())
        self.assertGreater(value.item(), 0)
        with self.assertRaises(Refusal):
            channels(value, scale)


if __name__ == "__main__":
    unittest.main()
