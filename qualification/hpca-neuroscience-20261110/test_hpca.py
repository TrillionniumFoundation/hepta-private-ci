"""HPCA adversarial invariants; synthetic diagnostics are never adoption gates."""
import unittest

from credit import run_credit
from replay import (prepare_source, current_source_lookup,
                    run_replay, POLICIES)
from schedules import (CALIBRATION_SEEDS, TEST_SEEDS, FAMILIES,
                       run_schedule, tune_rates)
from run import run_suite, source_manifest


class CreditTests(unittest.TestCase):
    def test_same_source_equal_information_strong_control(self):
        for delay in (0, 8):
            a = run_credit(17, routing="routed", delay=delay)
            b = run_credit(17, routing="context_gradient", delay=delay)
            self.assertEqual(a, b)

    def test_trace_modes_equal_when_feedback_immediate(self):
        a = run_credit(28, trace="event_id", delay=0)
        b = run_credit(28, trace="latest", delay=0)
        self.assertEqual(a, b)

    def test_shared_feedback_denominator(self):
        baseline = run_credit(29, routing="routed", delay=8)
        for route in ("random", "shuffled", "broadcast"):
            comparison = run_credit(29, routing=route, delay=8)
            self.assertEqual(comparison["feedback_count"],
                             baseline["feedback_count"])
            self.assertGreaterEqual(comparison["heldout_accuracy"], 0)
            self.assertLessEqual(comparison["heldout_accuracy"], 1)

    def test_broadcast_is_not_cost_matched(self):
        single = run_credit(4, routing="routed")
        all_groups = run_credit(4, routing="broadcast")
        self.assertEqual(all_groups["parameter_updates"],
                         3 * single["parameter_updates"])


class SchedulingTests(unittest.TestCase):
    def test_equal_aggregate_optimizer_budget(self):
        rates = {family: 0.12 for family in FAMILIES}
        a = run_schedule(7, "uniform", rates)
        b = run_schedule(7, "heterogeneous", rates)
        self.assertEqual(a["optimizer_updates"], 256)
        self.assertEqual(b["optimizer_updates"], 256)
        self.assertNotEqual(a["updates_by_family"],
                            b["updates_by_family"])

    def test_calibration_and_test_seeds_disjoint(self):
        self.assertFalse(set(CALIBRATION_SEEDS) & set(TEST_SEEDS))
        for policy in ("uniform", "heterogeneous"):
            selected = tune_rates(policy)
            self.assertEqual(set(selected), set(FAMILIES))
            self.assertTrue(all(0 < a < 1 for a in selected.values()))


class ReplayTests(unittest.TestCase):
    def test_tombstones_and_superseded_revision_not_replayed(self):
        old, new, index, tombstones = prepare_source(31)
        self.assertEqual(index[2].revision, 2)
        self.assertNotIn(2, {r.key for r in old})
        for key in tombstones:
            self.assertIsNone(current_source_lookup(index, tombstones, key))
        self.assertEqual(current_source_lookup(index, tombstones, 2),
                         index[2])
        for policy in POLICIES:
            result = run_replay(31, policy=policy)
            self.assertEqual(result["revoked_replayed"], 0)
            self.assertEqual(result["deleted_denied"], 2)

    def test_matched_model_update_budget_and_billed_scans(self):
        results = {p: run_replay(21, policy=p) for p in POLICIES}
        for p in ("recent", "uniform", "stratified", "error_priority"):
            self.assertEqual(results[p]["parameter_updates"], 560)
        self.assertEqual(results["exact_key"]["parameter_updates"], 0)
        self.assertGreater(results["error_priority"]["selection_reads"],
                           results["uniform"]["selection_reads"])
        self.assertEqual(results["exact_key"]["old_retention"], 1.0)


class OutputTests(unittest.TestCase):
    def test_immutable_report_and_no_go(self):
        a = run_suite(TEST_SEEDS[:2])
        b = run_suite(TEST_SEEDS[:2])
        self.assertEqual(a, b)
        self.assertEqual(a["decision"], "HOLD_NO_GO")
        self.assertEqual(a["schema"], "HEPTA-HPCA-MICRO-V1")
        self.assertEqual(len(a["source_manifest_sha256"]), 64)
        self.assertEqual(a["source_manifest_sha256"], source_manifest())
        self.assertEqual(a["schedule"]["per_arm_update_budget"], 256)


if __name__ == "__main__":
    unittest.main()
