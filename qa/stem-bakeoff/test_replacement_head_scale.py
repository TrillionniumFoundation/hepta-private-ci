"""Synthetic contract tests for original-Head CPU fanout; no real model claim."""
import math
import unittest
from unittest import mock

import replacement_head_scale as scale


class HeadScaleTests(unittest.TestCase):
    @staticmethod
    def _frozen_head():
        import torch

        torch.manual_seed(7)
        head = torch.nn.Linear(4, 4)
        for param in head.parameters():
            param.requires_grad_(False)
        return head.eval()

    def test_real_distinct_cpu_heads_and_raw_latencies(self):
        import torch

        head = self._frozen_head()
        with mock.patch.object(scale, "SCALES", (2, 4, 6, 8)):
            out = scale.measure_trained_head_fanout(
                head, torch.tensor([[1.0, 0.5, -0.25, 0.75]]),
                scales=(2, 4, 6, 8),
            )
        self.assertEqual(out["mode"], "SHADOW_ONLY")
        self.assertEqual(out["authority"], "DENY_ALL")
        self.assertFalse(out["production_activation_allowed"])
        self.assertFalse(out["target_device_qualified"])
        self.assertFalse(out["independent_input_event_scaling_measured"])
        self.assertEqual(out["model_encoder_forwards_within_probe"], 0)
        for count, row in zip((2, 4, 6, 8), out["measurements"], strict=True):
            self.assertEqual(row["logical_cells"], count)
            self.assertEqual(row["private_head_instances"], count)
            self.assertEqual(row["unique_parameter_storages"], 2 * count)
            self.assertEqual(row["head_calls_per_batch"], count)
            self.assertEqual(row["simultaneously_executing_heads"], 1)
            self.assertEqual(len(row["raw_full_fanout_latency_ms"]), 100)
            self.assertTrue(math.isfinite(row["head_outputs_per_second"]))
            self.assertLessEqual(row["full_batch_p50_ms"], row["full_batch_p99_ms"])
            self.assertGreater(row["process_high_water_rss_bytes"], 0)

    def test_wrong_scale_and_timing_sample_budget_rejected(self):
        import torch
        head = self._frozen_head()
        x = torch.zeros(1, 4)
        with self.assertRaisesRegex(ValueError, "fixed"):
            scale.measure_trained_head_fanout(head, x, scales=(64,))
        with self.assertRaisesRegex(ValueError, "fixed"):
            scale.measure_trained_head_fanout(head, x, samples=99)

    def test_unfrozen_or_training_mode_rejected(self):
        import torch
        head = self._frozen_head()
        head.train()
        with self.assertRaisesRegex(ValueError, "frozen"):
            scale.measure_trained_head_fanout(head, torch.ones(1, 4))
        head.eval()
        next(head.parameters()).requires_grad_(True)
        with self.assertRaisesRegex(ValueError, "frozen"):
            scale.measure_trained_head_fanout(head, torch.ones(1, 4))

    def test_invalid_or_nonfinite_source_feature_rejected(self):
        import torch
        head = self._frozen_head()
        for bad in (torch.ones(2, 4), torch.ones(1, 3),
                    torch.tensor([[float("nan"), 0., 0., 1.]]),
                    torch.ones(1, 4, dtype=torch.float64)):
            with self.assertRaisesRegex(ValueError, "preencoded"):
                scale.measure_trained_head_fanout(head, bad)

    def test_storage_aliasing_rejected(self):
        import torch
        head = self._frozen_head()
        with mock.patch.object(scale.copy, "deepcopy", return_value=head):
            with self.assertRaisesRegex(ValueError, "aliased"):
                scale.measure_trained_head_fanout(head, torch.ones(1, 4))

    def test_nonfinite_or_missing_raw_latency_rejected(self):
        for values in ([1.0] * 99, [1.0] * 99 + [float("inf")],
                       [1.0] * 99 + [0.0]):
            with self.assertRaisesRegex(ValueError, "100 genuine"):
                scale._quantile_nearest_rank(values, 0.99)


if __name__ == "__main__":
    unittest.main()
