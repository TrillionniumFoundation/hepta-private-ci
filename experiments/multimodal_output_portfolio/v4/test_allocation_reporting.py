"""Analytic fixtures for conditional, paired inference and budget reconciliation."""

import json
from pathlib import Path
import unittest

import numpy as np

from allocation_reporting import allocation_report, conditional_ce


def fixture():
    protocol = json.loads(Path(__file__).with_name("protocol.json").read_text())
    count = 64
    costs = np.full(count, 333824, dtype=np.int64)
    loss = np.repeat(np.linspace(.1, .5, 32), 2)
    value = -float(loss.mean()) - protocol["objective"]["mac_price_lambda"] * costs[0]
    records = {arm: {"world_id": np.arange(count), "loss": loss.copy(),
                    "per_modality_error": np.tile(loss[:, None], (1, 4)),
                    "contradiction": np.zeros(count), "macs": costs.copy(),
                    "refinement_counts": np.zeros((count, 4), np.int64)}
               for arm in protocol["policies"]["arms"]}
    planning = {"tree_and_clean_forward_linear_macs": 1705222144,
                "wall_seconds": 1., "process_cpu_seconds": 2.,
                "root_J": {arm: value for arm in records}}
    return protocol, {5: {"planning": planning, "arms": records}}, value


class ReportingTests(unittest.TestCase):
    def test_conditional_root_average_is_not_ce_of_pooled_roots(self):
        protocol, results, expected = fixture()
        report = allocation_report(results, protocol, development=True)
        self.assertAlmostEqual(report["arms"]["dynamic"]["sampled_J"], expected, places=14)
        record = results[5]["arms"]["dynamic"]
        pooled = conditional_ce(-record["loss"] - protocol["objective"]["mac_price_lambda"]
                                * record["macs"], 2., axis=0)
        self.assertLess(pooled, expected)
        for comparison in report["comparisons_dynamic_minus"].values():
            self.assertEqual(comparison["sampled_J_paired_stratified_bootstrap_95_interval"], [0., 0.])
        self.assertFalse(report["primary_superiority_passed"])

    def test_paired_world_noise_cancels_for_cash_translation(self):
        protocol, results, _ = fixture()
        for index, (arm, record) in enumerate(results[5]["arms"].items()):
            change = np.tile([0., .08], 32) + .01 * index
            record["loss"] += change
            record["per_modality_error"] += change[:, None]
        report = allocation_report(results, protocol, development=True)
        primary = report["comparisons_dynamic_minus"]["initial_feedback_committed_open_loop"]
        self.assertAlmostEqual(primary["sampled_J_difference"], .01, places=14)
        np.testing.assert_allclose(primary["sampled_J_paired_stratified_bootstrap_95_interval"],
                                   [.01, .01], rtol=0, atol=1e-14)

    def test_bad_budget_or_pairing_and_missing_seed_are_rejected(self):
        protocol, results, _ = fixture()
        record = results[5]["arms"]["dynamic"]
        record["macs"][0] += 1
        with self.assertRaises(ValueError):
            allocation_report(results, protocol, development=True)
        record["macs"][0] -= 1
        record["world_id"][[0, 1]] = [1, 0]
        with self.assertRaises(ValueError):
            allocation_report(results, protocol, development=True)
        with self.assertRaises(ValueError):
            allocation_report(results, protocol, development=False)


if __name__ == "__main__":
    unittest.main()
