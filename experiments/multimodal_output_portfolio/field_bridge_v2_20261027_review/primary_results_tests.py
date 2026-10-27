"""Synthetic causal-contrast acceptance guards; no experiment outcomes are read."""

import unittest

import numpy as np

from .primary_results_audit import ARMS, CONDITIONS, OBSERVERS, PAIRS, calculate


def fixture():
    offsets = (0., .01, .02, .01, .05, .03, .02, .01, .025, .02, .02)
    values, actions = {}, {}
    for split, conditions in CONDITIONS.items():
        for arm, offset in zip(ARMS, offsets):
            # Vary source-cluster baseline without changing paired constant effects.
            base = .6 + .1 * np.sin(np.arange(3 * PAIRS * len(conditions))).reshape(3, PAIRS, len(conditions))
            for observer in OBSERVERS:
                values[split, observer, arm] = base + (offset if split == "test" else 0)
            actions[split, arm] = np.ones_like(base, dtype=int)
    return values, actions


class PrimaryStatisticsTests(unittest.TestCase):
    def test_actual_positive_effects_and_retention_pass(self):
        values, actions = fixture()
        result = calculate(values, actions, 271031)
        self.assertTrue(result["all_six_primary_gains_accepted"])
        self.assertTrue(all(row["both_observers_noninferior"] for row in result["retention_vs_frozen"]))
        first = result["primary_contrasts"][0]["observers"]["reward"]
        self.assertAlmostEqual(first["mean_net_return_difference"], .01)
        self.assertAlmostEqual(first["pooled_ce_difference"], .01)
        self.assertAlmostEqual(result["interaction_descriptive"]["observers"]["reward"]["mean_net_return_interaction"], .02)

    def test_gain_cannot_override_failed_independent_retention(self):
        values, actions = fixture()
        values["retention", "audit", "E_field_native"] -= .02
        result = calculate(values, actions, 271031)
        matches = [r for r in result["primary_contrasts"] if r["candidate"] == "E_field_native"]
        self.assertTrue(all(row["both_observers_gain_supported"] for row in matches))
        self.assertTrue(all(not row["accepted_with_retention"] for row in matches))
        self.assertFalse(result["all_six_primary_gains_accepted"])

    def test_positive_pooled_interval_cannot_hide_adverse_seed(self):
        values, actions = fixture()
        for observer in OBSERVERS:
            values["test", observer, "D_frozen_native"][0] -= .015
        result = calculate(values, actions, 271031)
        contrast = result["primary_contrasts"][2]
        for score in contrast["observers"].values():
            self.assertGreater(score["paired_cluster_interval"][0], 0)
            self.assertFalse(score["positive_in_every_fixed_seed"])
            self.assertFalse(score["gain_supported"])
        self.assertFalse(contrast["accepted_with_retention"])


if __name__ == "__main__":
    unittest.main()
