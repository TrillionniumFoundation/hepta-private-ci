"""Local physically executed tiny CPU Head tests; no pretrained model calls."""
import copy
import hashlib
from pathlib import Path
import unittest

from stem_v7_physical_heads import (
    SIZE_LEVELS, gated_head_count, _tensors, head_forward, measured_child,
    validate_physical_receipt,
)


class PhysicalHeadTests(unittest.TestCase):
    def test_parameter_count(self):
        self.assertEqual(gated_head_count(), 6_914)
        self.assertEqual(gated_head_count(16, 2), 98)

    def test_real_torch_head_forward_is_repeatable(self):
        import torch
        w = _tensors(64)
        x = torch.linspace(-1, 1, 384, dtype=torch.float32)
        ids = torch.tensor([0, 3, 17], dtype=torch.long)
        with torch.no_grad():
            a = head_forward(w, x, ids)
            b = head_forward(w, x, ids)
        self.assertTrue(torch.equal(a, b))
        self.assertEqual(tuple(a.shape), (3,))

    def test_pretrained_encoder_is_not_claimed(self):
        row = measured_child(64)
        self.assertEqual(row["actual_allocated_head_params"], 64 * 6914)
        self.assertEqual(row["encoder_forward_calls"], 0)
        self.assertFalse(row["head_quality_verified"])
        self.assertTrue(validate_physical_receipt(row))

    def test_reject_overclaimed_dot_and_encoder(self):
        row = measured_child(64)
        for name, value in (("real_pretrained_encoder_forward", True),
                            ("target_dot_host_verified", True), ("encoder_forward_calls", 1)):
            bad = copy.deepcopy(row)
            bad[name] = value
            with self.assertRaises(ValueError): validate_physical_receipt(bad)

    def test_reject_counter_and_performance_tampering(self):
        row = measured_child(64)
        for name, value in (("actual_allocated_head_params", 4096), ("actual_head_tensors", 4),
                            ("source_feature_buffers", 64)):
            bad = copy.deepcopy(row)
            bad[name] = value
            with self.assertRaises(ValueError): validate_physical_receipt(bad)
        bad = copy.deepcopy(row)
        bad["latency_ms"]["p95"] = float("nan")
        with self.assertRaises(ValueError): validate_physical_receipt(bad)
        bad = copy.deepcopy(row)
        bad["script_sha256"] = "0" * 64
        with self.assertRaises(ValueError): validate_physical_receipt(bad, expected_script_sha256=hashlib.sha256(Path(__import__('stem_v7_physical_heads').__file__).read_bytes()).hexdigest())

    def test_fleet_levels_registered(self):
        self.assertEqual(SIZE_LEVELS, (64, 256, 1024, 4096))


if __name__ == "__main__":
    unittest.main()
