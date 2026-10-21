"""Adversarial regressions for the explicitly untrained Stem fan-out probe."""
import pathlib
import sys
import unittest

try:
    import torch
except ImportError:
    torch = None

if torch is not None:
    sys.path.insert(0, str(pathlib.Path(__file__).parent))
    from scale_probe import SCALES, _percentile, probe
    from native_latent import StemContractError


@unittest.skipUnless(torch is not None, "optional PyTorch CPU smoke")
class ScaleProbeTests(unittest.TestCase):
    def test_fanout_counts_and_non_authorizing_receipt(self):
        result = probe(scales=(1, 8, 64), repeats=2)
        self.assertEqual([r["cells"] for r in result["measurements"]], [1, 8, 64])
        self.assertEqual(len(result["plan_sha256"]), 64)
        self.assertFalse(result["may_satisfy_real_model_bakeoff_gate"])
        self.assertFalse(result["production_activation_allowed"])
        self.assertFalse(result["model_pretrained"])
        self.assertFalse(result["energy_measured"])
        self.assertEqual(result["runtime_posture"]["authority"], "DENY_ALL")
        for row in result["measurements"]:
            self.assertEqual(row["owner_forward_calls"], 2)
            self.assertEqual(row["module_forward_hook_calls"], 2)
            self.assertEqual(row["private_backbone_instances_detected"], 0)
            self.assertGreater(row["per_cell_head_parameters"], 0)
            self.assertGreater(row["process_lifetime_peak_rss_bytes"], 0)
            self.assertLessEqual(row["p50_ms"], row["p95_ms"])
            self.assertLessEqual(row["p95_ms"], row["p99_ms"])

    def test_rejects_unregistered_repeated_out_of_order_or_boolean_scales(self):
        for scales in ((4096, 1), (1, 1), (1, 7), (True, 8), (0, 1), (), [1, 8]):
            with self.subTest(scales=scales), self.assertRaises(StemContractError):
                probe(scales=scales)
        for value in (0, 9, True, 1.5):
            with self.subTest(repeats=value), self.assertRaises(StemContractError):
                probe(scales=(1,), repeats=value)

    def test_percentile_interpolates_exact_observations(self):
        self.assertEqual(_percentile([1.0, 3.0], 50), 2.0)
        self.assertEqual(_percentile([1.0, 3.0], 99), 2.98)
        with self.assertRaises(StemContractError):
            _percentile([float("nan")], 99)

    def test_full_scale_definition_is_stable(self):
        self.assertEqual(SCALES, (1, 8, 64, 256, 1024, 4096))


if __name__ == "__main__":
    unittest.main()
