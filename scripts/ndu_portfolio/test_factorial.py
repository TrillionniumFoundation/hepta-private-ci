"""Adversarial tests of scientific admission and immutable comparator selection."""

import copy
import unittest

from .example_factorial import example
from .factorial import (
    TIMING_TOLERANCE_SECONDS,
    InvalidEvidence,
    audit,
    select_comparators,
    validate_protocol,
)


class FactorialGates(unittest.TestCase):
    def setUp(self):
        self.p, self.rows, self.lock = example()

    def relock(self):
        self.lock = select_comparators(
            self.p,
            [row for row in self.rows if row["split"] == "validation"],
            "2026-11-03T00:00:00Z",
        )

    def test_synthetic_stays_hold_with_positive_arithmetic(self):
        out = audit(self.p, self.rows, self.lock)
        self.assertTrue(out["matrix_complete"])
        self.assertEqual(set(out["scientific_gates"].values()), {"HOLD"})
        self.assertEqual(out["contrasts"]["joint:D-B"]["statistical_gate"], "PASS")
        self.assertEqual(out["contrasts"]["frozen:interaction"]["clusters"], 20)
        self.assertFalse(out["adoption_authorized"])
        self.assertEqual(out["contrasts"]["joint:D-B"]["gate"], "HOLD")

    def test_self_reported_real_does_not_verify_native_evidence(self):
        self.p["evidence_kind"] = "real"
        self.p["native_receipts_verified"] = True
        self.relock()
        out = audit(self.p, self.rows, self.lock)
        self.assertEqual(
            out["conditional_gates_on_verified_receipts"]["hepta_increment"], "PASS"
        )
        self.assertEqual(set(out["scientific_gates"].values()), {"HOLD"})
        self.assertFalse(out["native_receipt_verification"]["verified"])
        self.assertEqual(
            out["native_receipt_verification"]["status"], "NOT_IMPLEMENTED"
        )
        self.assertTrue(all(c["gate"] == "HOLD" for c in out["contrasts"].values()))
        self.assertFalse(out["adoption_authorized"])

    def test_missing_failed_row_is_rejected(self):
        row = self.rows[-1]
        row.update(status="failed", failed_attempts=1, external_score=0)
        out = audit(self.p, self.rows, self.lock)
        self.assertEqual(out["failed_episodes"], 1)
        with self.assertRaisesRegex(InvalidEvidence, "incomplete"):
            audit(self.p, self.rows[:-1], self.lock)

    def test_unknown_test_cost_keeps_null_and_hold(self):
        self.rows[-1]["costs"]["sync"] = None
        out = audit(self.p, self.rows, self.lock)
        self.assertTrue(out["unknowns"])
        self.assertEqual(set(out["scientific_gates"].values()), {"HOLD"})

    def test_unknown_research_cost_does_not_prevent_validation_lock(self):
        self.p["profiles"]["joint:D"]["research_costs"]["evaluation"] = None
        lock = select_comparators(self.p, self.rows[:1280], "2026-11-03T00:00:00Z")
        self.assertEqual(lock, self.lock)
        out = audit(self.p, self.rows, lock)
        self.assertIsNone(out["research_costs"]["joint:D"]["total"])
        self.assertIsNone(
            out["D_minus_strongest_amortized_at_deployments"]["joint"]["100"]
        )

    def test_observed_training_usage_is_frozen_in_selection(self):
        self.p["profiles"]["joint:D"]["training_actual"]["train_compute"] += 1
        with self.assertRaisesRegex(InvalidEvidence, "lock does not match"):
            audit(self.p, self.rows, self.lock)

    def test_completed_training_and_search_costs_cannot_change_after_selection(self):
        for component in ("training", "search"):
            with self.subTest(component=component):
                protocol = copy.deepcopy(self.p)
                protocol["profiles"]["joint:D"]["research_costs"][component] += 1
                with self.assertRaisesRegex(InvalidEvidence, "lock does not match"):
                    audit(protocol, self.rows, self.lock)

    def test_null_pre_evaluation_receipts_cannot_be_filled_after_selection(self):
        for category, field in (
            ("training_actual", "train_compute"),
            ("research_costs", "training"),
            ("research_costs", "search"),
        ):
            with self.subTest(category=category, field=field):
                protocol = copy.deepcopy(self.p)
                original = protocol["profiles"]["joint:D"][category][field]
                protocol["profiles"]["joint:D"][category][field] = None
                lock = select_comparators(
                    protocol, self.rows[:1280], "2026-11-03T00:00:00Z"
                )
                self.assertIsNone(
                    lock["pre_evaluation_receipts"]["joint:D"][category][field]
                )
                out = audit(protocol, self.rows, lock)
                self.assertEqual(
                    set(out["conditional_gates_on_verified_receipts"].values()),
                    {"HOLD"},
                )
                protocol["profiles"]["joint:D"][category][field] = original
                with self.assertRaisesRegex(InvalidEvidence, "lock does not match"):
                    audit(protocol, self.rows, lock)

    def test_evaluation_expenditure_can_be_completed_after_selection(self):
        self.p["profiles"]["joint:D"]["research_costs"]["evaluation"] = None
        self.relock()
        self.p["profiles"]["joint:D"]["research_costs"]["evaluation"] = 20
        out = audit(self.p, self.rows, self.lock)
        self.assertEqual(out["research_costs"]["joint:D"]["total"], 130)
        self.assertEqual(out["unknowns"], [])

    def test_unknown_cost_ledger_never_zero_fills(self):
        self.rows[-1]["costs"]["sync"] = None
        out = audit(self.p, self.rows, self.lock)
        ledger = out["inference_cost_ledger"]["all_observed_episodes"]
        self.assertIsNone(ledger["total"])
        self.assertIsNone(ledger["components"]["sync"]["total"])
        self.assertEqual(ledger["components"]["sync"]["unknown_episodes"], 1)
        self.assertTrue(all(c["gate"] == "HOLD" for c in out["contrasts"].values()))

    def test_frozen_model_confounded_controller_rejected(self):
        self.p["profiles"]["frozen:B"]["model_digest"] = "f" * 64
        with self.assertRaisesRegex(InvalidEvidence, "same content model"):
            validate_protocol(self.p)

    def test_same_source_cannot_manufacture_clusters(self):
        self.p["tasks"][-1]["source_group"] = self.p["tasks"][-2]["source_group"]
        with self.assertRaisesRegex(InvalidEvidence, "relabelled"):
            validate_protocol(self.p)

    def test_unknown_training_budget_rejected(self):
        self.p["profiles"]["joint:D"]["budget"]["search_trials"] = None
        with self.assertRaisesRegex(InvalidEvidence, "budget search_trials"):
            validate_protocol(self.p)

    def test_unequal_declared_budget_still_rejected(self):
        self.p["profiles"]["joint:D"]["budget"]["episode_cost"] += 1
        with self.assertRaisesRegex(InvalidEvidence, "capacity/budget mismatch"):
            validate_protocol(self.p)

    def test_step_pseudoreplication_rejected(self):
        self.rows[-1]["row_type"] = "step"
        with self.assertRaisesRegex(InvalidEvidence, "step rows"):
            audit(self.p, self.rows, self.lock)

    def test_duplicate_episode_rejected(self):
        with self.assertRaisesRegex(InvalidEvidence, "duplicate episode"):
            audit(self.p, self.rows + [copy.deepcopy(self.rows[-1])], self.lock)

    def test_source_group_leak_rejected(self):
        self.p["tasks"][-1]["source_group"] = self.p["tasks"][0]["source_group"]
        with self.assertRaisesRegex(InvalidEvidence, "cross-split leakage"):
            validate_protocol(self.p)

    def test_capacity_mismatch_rejected(self):
        self.p["profiles"]["joint:D"]["active_parameters"] += 1
        with self.assertRaisesRegex(InvalidEvidence, "capacity/budget mismatch"):
            validate_protocol(self.p)

    def test_risk_profile_alias_rejected(self):
        self.p["profiles"]["joint:B"]["risk_profile_id"] = "population-entropic-v3"
        with self.assertRaisesRegex(InvalidEvidence, "risk profile mismatch"):
            validate_protocol(self.p)

    def test_risk_neutral_router_objective_rejected(self):
        self.p["profiles"]["joint:B"]["objective_digest"] = "0" * 64
        with self.assertRaisesRegex(InvalidEvidence, "objective mismatch"):
            validate_protocol(self.p)

    def test_heldout_baseline_switch_rejected(self):
        self.lock["choices"]["joint"]["complete"] = "initial"
        with self.assertRaisesRegex(InvalidEvidence, "lock does not match"):
            audit(self.p, self.rows, self.lock)

    def test_retroactive_lock_rejected(self):
        lock = select_comparators(self.p, self.rows[:1280], "2026-11-05T00:00:00Z")
        with self.assertRaisesRegex(InvalidEvidence, "test observed before"):
            audit(self.p, self.rows, lock)

    def test_strongest_validation_comparator_is_mpc(self):
        self.assertEqual(
            self.lock["choices"],
            {r: {"ordinary": "mpc", "complete": "mpc"} for r in ("frozen", "joint")},
        )
        for row in self.rows:
            if row["split"] == "test" and row["arm"] == "initial":
                row["external_score"] = 1.0
        out = audit(self.p, self.rows, self.lock)
        self.assertEqual(out["comparators"], self.lock["choices"])

    def test_failed_score_must_use_fixed_penalty(self):
        self.rows[-1].update(status="failed", failed_attempts=1, external_score=0.9)
        with self.assertRaisesRegex(InvalidEvidence, "fixed failure score"):
            audit(self.p, self.rows, self.lock)

    def test_episode_overruns_retain_failure_denominator_costs_and_diagnostics(self):
        self.p["evidence_kind"] = "real"
        self.relock()
        row = self.rows[-1]
        row.update(
            status="failed",
            failed_attempts=1,
            external_score=0,
            latency_seconds=11,
            peak_bytes=1048577,
            finished_at="2026-11-04T01:00:11Z",
        )
        row["costs"]["planning"] = 101
        out = audit(self.p, self.rows, self.lock)
        self.assertTrue(out["matrix_complete"])
        self.assertEqual(out["episode_count"], 2560)
        self.assertEqual(out["failed_episodes"], 1)
        self.assertEqual(
            {v["metric"] for v in out["budget_violations"]},
            {"episode_cost", "latency_seconds", "peak_bytes", "timestamp_span_seconds"},
        )
        self.assertEqual(out["integrity_violations"], [])
        ledger = out["inference_cost_ledger"]["all_observed_episodes"]
        self.assertEqual(ledger["episodes"], 2560)
        self.assertEqual(ledger["failed_episodes"], 1)
        self.assertAlmostEqual(ledger["total"], 2404.9, places=6)
        self.assertEqual(out["contrasts"]["joint:D-B"]["statistical_gate"], "PASS")
        self.assertEqual(
            set(out["conditional_gates_on_verified_receipts"].values()), {"HOLD"}
        )
        self.assertEqual(set(out["scientific_gates"].values()), {"HOLD"})

    def test_validation_overrun_is_retained_and_blocks_conditional_admission(self):
        self.p["evidence_kind"] = "real"
        self.rows[0]["costs"]["planning"] = 101
        self.relock()
        out = audit(self.p, self.rows, self.lock)
        self.assertEqual(out["episode_count"], 2560)
        self.assertEqual(out["budget_violations"][0]["run_id"], self.rows[0]["run_id"])
        self.assertEqual(
            set(out["conditional_gates_on_verified_receipts"].values()), {"HOLD"}
        )

    def test_training_usage_overruns_retain_observed_values(self):
        self.p["evidence_kind"] = "real"
        profile = self.p["profiles"]["joint:D"]
        for field in ("train_compute", "train_examples", "search_trials"):
            profile["training_actual"][field] = profile["budget"][field] + 1
        self.relock()
        out = audit(self.p, self.rows, self.lock)
        violations = out["budget_violations"]
        self.assertEqual(len(violations), 3)
        self.assertTrue(
            all(
                v["scope"] == "training" and v["profile"] == "joint:D"
                for v in violations
            )
        )
        self.assertTrue(all(v["observed"] == v["limit"] + 1 for v in violations))
        self.assertEqual(out["episode_count"], 2560)
        self.assertEqual(out["research_costs"]["joint:D"]["total"], 120)
        self.assertEqual(out["contrasts"]["joint:D-B"]["statistical_gate"], "PASS")
        self.assertEqual(
            set(out["conditional_gates_on_verified_receipts"].values()), {"HOLD"}
        )

    def test_partial_cost_overrun_remains_explicit_lower_bound_and_null_total(self):
        self.rows[-1]["costs"].update(planning=101, sync=None)
        out = audit(self.p, self.rows, self.lock)
        self.assertTrue(out["budget_violations"][0]["observed_is_lower_bound"])
        self.assertIsNone(
            out["inference_cost_ledger"]["all_observed_episodes"]["total"]
        )
        self.assertEqual(out["episode_count"], 2560)

    def test_hour_timestamp_cannot_be_reported_as_one_second(self):
        self.p["evidence_kind"] = "real"
        self.relock()
        self.rows[-1]["finished_at"] = "2026-11-04T02:00:00Z"
        out = audit(self.p, self.rows, self.lock)
        violation = out["integrity_violations"][0]
        self.assertEqual(violation["code"], "latency_timestamp_mismatch")
        self.assertEqual(violation["declared_latency_seconds"], 1)
        self.assertEqual(violation["timestamp_span_seconds"], 3600)
        self.assertEqual(violation["tolerance_seconds"], TIMING_TOLERANCE_SECONDS)
        self.assertEqual(
            out["budget_violations"][0]["metric"], "timestamp_span_seconds"
        )
        self.assertEqual(out["episode_count"], 2560)
        self.assertAlmostEqual(
            out["inference_cost_ledger"]["all_observed_episodes"]["total"],
            2304,
            places=6,
        )
        self.assertEqual(
            set(out["conditional_gates_on_verified_receipts"].values()), {"HOLD"}
        )

    def test_timing_tolerance_is_fixed_absolute_one_millisecond(self):
        for difference, expected_count in ((0.0005, 0), (0.002, 1)):
            with self.subTest(difference=difference):
                self.rows[-1]["latency_seconds"] = 1 + difference
                out = audit(self.p, self.rows, self.lock)
                self.assertEqual(len(out["integrity_violations"]), expected_count)
                self.assertEqual(
                    out["timing_check"]["absolute_tolerance_seconds"], 0.001
                )
                self.assertEqual(out["timing_check"]["relative_tolerance"], 0)

    def test_reversed_timing_keeps_the_episode_and_costs(self):
        self.rows[-1]["finished_at"] = "2026-11-04T00:59:59Z"
        out = audit(self.p, self.rows, self.lock)
        self.assertEqual(
            out["integrity_violations"][0]["code"], "reversed_episode_time"
        )
        self.assertEqual(out["episode_count"], 2560)
        self.assertAlmostEqual(
            out["inference_cost_ledger"]["all_observed_episodes"]["total"],
            2304,
            places=6,
        )

    def test_unmeasured_failure_and_retry_charges_are_never_zero_filled(self):
        row = self.rows[-1]
        row.update(status="failed", failed_attempts=1, external_score=0)
        row["costs"].update(failure=None, retry=None)
        out = audit(self.p, self.rows, self.lock)
        self.assertEqual(out["failed_episodes"], 1)
        ledger = out["inference_cost_ledger"]["all_observed_episodes"]
        self.assertIsNone(ledger["components"]["failure"]["total"])
        self.assertIsNone(ledger["components"]["retry"]["total"])
        self.assertIsNone(ledger["total"])
        self.assertEqual(
            set(out["conditional_gates_on_verified_receipts"].values()), {"HOLD"}
        )

    def test_nan_cost_rejected(self):
        self.rows[-1]["costs"]["encoder"] = float("nan")
        with self.assertRaisesRegex(InvalidEvidence, "invalid encoder"):
            audit(self.p, self.rows, self.lock)

    def test_extra_attempt_identity_reuse_rejected(self):
        self.rows[-1]["attempt_ids"] = self.rows[-2]["attempt_ids"]
        with self.assertRaisesRegex(InvalidEvidence, "reused attempt"):
            audit(self.p, self.rows, self.lock)

    def test_unequal_cluster_size_not_step_weighted(self):
        # Two seeds remain one cluster; the CI counts source clusters, not rows.
        out = audit(self.p, self.rows, self.lock)
        self.assertEqual(out["episode_count"], 2560)
        self.assertEqual(out["contrasts"]["joint:D-B"]["clusters"], 20)
        self.assertAlmostEqual(out["contrasts"]["frozen:D-B"]["estimate"], 0.2)
        self.assertAlmostEqual(out["contrasts"]["joint:interaction"]["estimate"], 0.24)


if __name__ == "__main__":
    unittest.main()
