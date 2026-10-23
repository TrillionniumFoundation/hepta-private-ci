"""Handmade algebra checks; no dataset, model or actual timing."""

import importlib.util
from pathlib import Path
import unittest


SPEC = importlib.util.spec_from_file_location("h2_analysis", Path(__file__).with_name("analyze.py"))
a = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(a)


def fixture(gain, gap=.001, go_ns=110000., stop_ns=100000.):
    g = list(gain) * (3072 // len(gain))
    low = [.7] * 3072
    full = [.7 + value for value in g]
    arrays = {"s11_NC_low": low, "s11_NC_full": full, "s11_NC_delta": g,
              "s11_N_full": [value + gap for value in full]}
    reports = {}
    for repeat in range(3):
        for path, cpu in (("NC-full", 90000.), ("NC-go", go_ns),
                          ("NC-stop", stop_ns), ("N-full", 80000.)):
            reports[(repeat, 11, path)] = {"cost": {"cpu_ns": cpu * 3072, "prepare_cpu_ns": 1000000}}
    return arrays, reports


class AlgebraTests(unittest.TestCase):
    def test_all_continue_cannot_hide_content_and_mandatory_cost_gap(self):
        arrays, reports = fixture([.1], gap=.01, go_ns=200000.)
        row = a.seed_summary(11, arrays, reports)
        self.assertEqual(row["oracle_continue_fraction"], 1)
        self.assertEqual(row["oracle_headroom_vs_own_continue_proxy"], 0)
        expected = -.01 - a.priced(120000.) - a.priced((8.537556029 - 8.307966292) * 1e9 / 300000)
        self.assertAlmostEqual(row["oracle_proxy_net_minus_direct_N_full"], expected, places=12)
        self.assertAlmostEqual(sum(value for key, value in row["decomposition"].items()
                                   if key != "sum"), expected, places=12)

    def test_crossing_oracle_keeps_every_timing_sample(self):
        arrays, reports = fixture([-.01, .01])
        row = a.seed_summary(11, arrays, reports)
        c = a.priced(10000.)
        self.assertAlmostEqual(row["oracle_headroom_vs_own_continue_proxy"], (.01 + c) / 2)
        self.assertAlmostEqual(row["oracle_headroom_vs_own_stop_proxy"], (.01 - c) / 2)
        self.assertEqual(row["oracle_stop_rows"], 1536)
        self.assertAlmostEqual(row["free_label_oracle_raw_minus_N_full"], .004)
        self.assertEqual(row["signed_go_minus_stop_cpu_ns_per_row"], [10000.] * 3)
        self.assertEqual(len(row["all_timing_samples"]), 4)

    def test_negative_measured_increment_retained_without_free_compute_claim(self):
        arrays, reports = fixture([-.01, .01], go_ns=99000.)
        row = a.seed_summary(11, arrays, reports)
        self.assertEqual(row["signed_median_marginal_cpu_ns_per_row"], -1000.)
        self.assertEqual(row["new_wave_service_price_c"], 0.)
        self.assertEqual(row["signed_go_minus_stop_cpu_ns_per_row"], [-1000.] * 3)
        self.assertGreater(row["signed_price_sensitivity_oracle_minus_N_full"],
                           row["oracle_proxy_net_minus_direct_N_full"])
        self.assertIn("not certified", row["limits"])


if __name__ == "__main__":
    unittest.main()
