"""Adversarial result-reader controls; every metric here is fixture data."""

from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from .comparison import ARMS, Attempt, Design, compare
from .inventory import START_FIELDS, START_SCHEMA, TERMINAL_SCHEMA, scan_inventory


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.design = Design("fixture", "h4-d1", (0, 1, 2), "1"*64, "2"*64,
                             "3"*64, "4"*64, "5"*64, 10, 4, 20, 8, 4, 0.01)
        quality = {"A": 0.1, "B": 0.2, "C": 0.4, "D": 0.8}
        self.rows = [Attempt(arm, seed, f"{arm}-{seed}", self.design.identity(),
                            str(seed+5)*64, "completed", 10, 4, 20, 160, 4,
                            100., 50. if arm == "D" else 100.,
                            quality[arm], 0.01 if arm == "D" else 0.02)
                     for arm in ARMS for seed in self.design.seeds]

    def verified(self, rows):
        with tempfile.TemporaryDirectory() as directory:
            for row in rows:
                values = asdict(row)
                start = dict(schema=START_SCHEMA, **{key: values[key] for key in START_FIELDS})
                raw = json.dumps(start, sort_keys=True).encode()
                (Path(directory)/f"{row.attempt_id}.start.json").write_bytes(raw)
                terminal = {"schema": TERMINAL_SCHEMA,
                            "start_sha256": hashlib.sha256(raw).hexdigest(), "attempt": values}
                (Path(directory)/f"{row.attempt_id}.terminal.json").write_text(json.dumps(terminal))
            observed, inventory = scan_inventory(directory, self.design)
            self.assertEqual(set(r.attempt_id for r in observed), set(r.attempt_id for r in rows))
            return compare(self.design, rows, inventory=inventory)

    def test_four_paired_effects_and_interaction(self):
        report = self.verified(self.rows)
        self.assertEqual(report["expected_identities"], 12)
        self.assertEqual(report["status"], "complete_paired_analysis")
        self.assertAlmostEqual(report["contrasts"]["kernel_feedback_D_minus_B"]["mean"], 0.6)
        self.assertAlmostEqual(report["contrasts"]["interaction_D_minus_C_minus_B_plus_A"]["mean"], 0.3)
        self.assertTrue(report["quality_latency_energy_gain"])

    def test_missing_arm_never_drops_the_denominator(self):
        report = compare(self.design, self.rows[:-1])
        self.assertEqual(report["missing"], [["D", 2]])
        self.assertEqual(report["expected_identities"], 12)
        self.assertIsNone(report["contrasts"])

    def test_failure_and_oom_costs_survive_completed_final(self):
        extra = replace(self.rows[0], attempt_id="oom-control", status="oom",
                        optimizer_updates=0, submitted_examples=0, tuning_updates=0,
                        total_wall_seconds=7., energy_joules=14.,
                        higher_is_better_quality=None, inference_p95_seconds=None)
        report = compare(self.design, [extra]+self.rows)
        cost = report["costs_by_identity"][0]
        self.assertEqual((cost["total_wall_seconds"], cost["energy_joules"]), (107., 114.))
        self.assertEqual(report["outcomes"]["oom"], 1)
        self.assertEqual(report["observed_attempts"], 13)

    def test_missing_physical_energy_cannot_pass_net_gate(self):
        rows = [replace(row, energy_joules=None) for row in self.rows]
        report = compare(self.design, rows)
        self.assertIsNotNone(report["contrasts"])
        self.assertIsNone(report["D_over_B_total_energy_log_ratio"])
        self.assertFalse(report["quality_latency_energy_gain"])

    def test_unknown_cost_blocks_comparison_without_imputation(self):
        rows = [replace(self.rows[0], total_wall_seconds=None)]+self.rows[1:]
        report = compare(self.design, rows)
        self.assertIn(["A", 0, "total_wall_seconds"], report["unknown_costs"])
        self.assertIsNone(report["contrasts"])

    def test_unknown_attempt_even_with_counters_is_not_terminal(self):
        extra = replace(self.rows[0], attempt_id="lost-reply", status="unknown",
                        optimizer_updates=0, submitted_examples=0, tuning_updates=0,
                        higher_is_better_quality=None, inference_p95_seconds=None)
        report = compare(self.design, self.rows+[extra])
        self.assertEqual(report["outcomes"]["unknown"], 1)
        self.assertIsNone(report["contrasts"])

    def test_partial_training_and_excess_retry_budget_block(self):
        rows = [replace(self.rows[0], optimizer_updates=19)]+self.rows[1:]
        self.assertIsNone(compare(self.design, rows)["contrasts"])
        extra = replace(self.rows[0], attempt_id="failed-recompute", status="failed",
                        optimizer_updates=1, submitted_examples=8, tuning_updates=0,
                        higher_is_better_quality=None, inference_p95_seconds=None)
        report = compare(self.design, [extra]+self.rows)
        self.assertTrue(report["budget_errors"])
        self.assertIsNone(report["contrasts"])

    def test_same_search_cap_with_unequal_realized_search_is_rejected(self):
        rows = [replace(self.rows[0], tuning_updates=3)]+self.rows[1:]
        report = compare(self.design, rows)
        self.assertEqual(report["budget_errors"], [[0, "unmatched realized tuning"]])

    def test_bad_capacity_initialization_and_design_are_rejected(self):
        for changes in ({"active_parameters": 11}, {"state_scalars": 5},
                        {"shared_initialization_sha256": "f"*64},
                        {"design_sha256": "a"*64}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                compare(self.design, [replace(self.rows[0], **changes)]+self.rows[1:])

    def test_duplicates_and_best_of_restarts_are_rejected(self):
        with self.assertRaises(ValueError):
            compare(self.design, self.rows+[self.rows[0]])
        with self.assertRaises(ValueError):
            compare(self.design, self.rows+[replace(self.rows[0], attempt_id="second-best")])

    def test_no_gain_without_prespecified_quality_and_latency(self):
        for changes in ({"higher_is_better_quality": 0.2}, {"inference_p95_seconds": 0.03}):
            rows = [replace(row, **changes) if row.arm == "D" else row for row in self.rows]
            self.assertFalse(self.verified(rows)["quality_latency_energy_gain"])

    def test_a_complete_list_is_not_a_closed_attempt_ledger(self):
        report = compare(self.design, self.rows)
        self.assertEqual(report["status"], "unqualified_paired_analysis")
        self.assertFalse(report["complete_attempt_costs_verified"])
        self.assertFalse(report["quality_latency_energy_gain"])

    def test_extreme_finite_quality_and_cost_cannot_emit_nan_report(self):
        rows = [replace(r, higher_is_better_quality=-1e308 if r.arm == "B" else 1e308)
                for r in self.rows]
        with self.assertRaises(FloatingPointError):
            compare(self.design, rows)
        extra = replace(self.rows[0], attempt_id="cost-overflow", status="failed",
                        optimizer_updates=0, submitted_examples=0, tuning_updates=0,
                        total_wall_seconds=1e308, higher_is_better_quality=None,
                        inference_p95_seconds=None)
        with self.assertRaises(ValueError):
            compare(self.design, [replace(self.rows[0], total_wall_seconds=1e308)]
                    +self.rows[1:]+[extra])

    def test_log_ratio_avoids_intermediate_underflow(self):
        rows = [replace(r, inference_p95_seconds=1e-300 if r.arm == "D" else 1e300)
                for r in self.rows]
        report = self.verified(rows)
        self.assertLess(report["D_over_B_latency_log_ratio"]["upper"], -1000)
        json.dumps(report, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
