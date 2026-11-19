"""Counterexamples for causal accounting, not evidence of Cell benefit."""

import copy
import unittest

from .causal_protocol import COMMON_MATCHES, b_contrasts, match_contracts, protocol
from .causal_analysis import cost_inventory, paired_contrast


class CausalProtocolTests(unittest.TestCase):
    def setUp(self):
        self.fits = ["fit1", "fit2"]
        self.cases = [
            {
                "case_id": f"c{i}",
                "source_group_id": f"g{i}",
                "split": "development",
                "task_family": "retrieval",
            }
            for i in range(2)
        ]
        self.rows = [
            {
                **case,
                "fit_id": fit,
                "condition_id": arm,
                "original_operation_id": f"{fit}/{arm}/{case['case_id']}",
                "terminal_status": "Completed",
                "analysis_utility": value,
            }
            for fit in self.fits
            for arm, value in [("control", 0.4), ("candidate", 0.6)]
            for case in self.cases
        ]

    def analyze(self, rows=None):
        return paired_contrast(
            self.rows if rows is None else rows,
            {"candidate": 1, "control": -1},
            self.fits,
            self.cases,
            draws=100,
        )

    def test_duplicate_training_seed_rejected(self):
        with self.assertRaises(ValueError):
            protocol("a" * 40, "b" * 40, [42, 42])

    def test_interaction_cancels_additive_kernel_and_controller_effects(self):
        weights = b_contrasts()["kernel_controller_interaction/persistent"]
        values = {
            "ordinary/light/persistent": 0.1,
            "ordinary/ndu/persistent": 0.3,
            "hepta/light/persistent": 0.4,
            "hepta/ndu/persistent": 0.6,
        }
        self.assertAlmostEqual(sum(weights[k] * values[k] for k in weights), 0)

    def test_unmatched_training_opportunity_detected(self):
        arms = [
            {"arm_id": name, "matches": dict.fromkeys(COMMON_MATCHES, "a" * 64)}
            for name in ("single", "cell")
        ]
        arms[1]["matches"]["training_opportunity"] = "b" * 64
        report = match_contracts(arms)
        self.assertEqual(report["mismatches"], ["training_opportunity"])
        self.assertFalse(report["declared_matching"])

    def test_missing_original_blocks_estimate(self):
        result = self.analyze(self.rows[:-1])
        self.assertEqual((result["planned_rows"], result["observed_rows"]), (8, 7))
        self.assertIsNone(result["mean"])

    def test_unknown_is_not_zero_or_dropped(self):
        self.rows[0].update(analysis_utility=None, terminal_status="Unresolved")
        result = self.analyze()
        self.assertEqual(len(result["unknown_rows"]), 1)
        self.assertIsNone(result["interval"])

    def test_numeric_unrecognized_status_does_not_become_completed(self):
        self.rows[0]["terminal_status"] = "Unverified"
        self.assertIsNone(self.analyze()["mean"])

    def test_planning_baselines_are_explicit_contrasts(self):
        contrasts = b_contrasts()
        for mode in ("reset", "persistent"):
            for core in ("ordinary", "hepta"):
                for control in ("tuned_fixed", "voi", "mpc"):
                    self.assertEqual(
                        contrasts[f"ndu_vs_{control}/{core}/{mode}"],
                        {f"{core}/ndu/{mode}": 1, f"{core}/{control}/{mode}": -1},
                    )

    def test_duplicate_retry_cannot_replace_original(self):
        duplicate = {
            **self.rows[0],
            "original_operation_id": "retry",
            "analysis_utility": 1,
        }
        with self.assertRaises(ValueError):
            self.analyze(self.rows + [duplicate])

    def test_source_split_tampering_rejected(self):
        self.rows[0]["split"] = "retention_validation"
        with self.assertRaises(ValueError):
            self.analyze()

    def test_episode_count_does_not_inflate_fits(self):
        result = self.analyze()
        self.assertEqual(result["independent_fit_count"], 2)
        self.assertAlmostEqual(result["mean"], 0.2)
        self.assertEqual(result["scientific_acceptance"], "HOLD")

    def test_cost_nested_envelope_not_double_counted(self):
        outer = {
            "event_id": "outer",
            "stage": "training",
            "methods": ["control", "cell"],
            "parent_event_id": None,
            "measurements": {
                "wall_seconds": 10,
                "cpu_seconds": 12,
                "energy_joules": None,
                "provider_charges": None,
            },
        }
        child = {
            **copy.deepcopy(outer),
            "event_id": "child",
            "stage": "controller",
            "parent_event_id": "outer",
        }
        child["measurements"]["wall_seconds"] = 3
        result = cost_inventory(
            [outer, child], ["control", "cell"], ("training", "controller")
        )
        self.assertEqual(
            result["physical_campaign"]["wall_seconds"]["observed_sum"], 10
        )
        self.assertEqual(
            result["methods"]["cell"]["measurements"]["wall_seconds"]["observed_sum"],
            10,
        )
        self.assertFalse(result["whole_budget_complete"])

    def test_cost_cycles_and_mixed_charge_units_rejected(self):
        a = {
            "event_id": "a",
            "stage": "training",
            "methods": ["cell"],
            "parent_event_id": "b",
            "provider_charges_unit": "USD",
            "measurements": dict(
                wall_seconds=1, cpu_seconds=1, energy_joules=1, provider_charges=1
            ),
        }
        b = {**copy.deepcopy(a), "event_id": "b", "parent_event_id": "a"}
        with self.assertRaises(ValueError):
            cost_inventory([a, b], ["cell"], ("training",))
        a["parent_event_id"] = b["parent_event_id"] = None
        b["provider_charges_unit"] = "compute_units"
        with self.assertRaises(ValueError):
            cost_inventory([a, b], ["cell"], ("training",))


if __name__ == "__main__":
    unittest.main()
