import copy
import unittest
from unittest.mock import patch

from reader_budget import (Budget, BudgetExceeded, allocate_shared_feature_cost,
                           freeze_frontier_bins, summarize_work_frontier)


def budget(**changes):
    args = dict(max_steps=2, max_callbacks=8, max_formula_flops=100, max_wall_ns=1000,
                registered_upper={p: dict(formula_flops=20, wall_ns=100, source_id="upper:v1")
                                  for p in ("propose", "verify", "critic", "native")})
    return Budget(**{**args, **changes})


def work(**changes):
    return dict(formula_flops=10, formula_source="operator_formula_complete.v1",
                source_id="operator-meter:v1", **changes)


def debit(b, phase="propose", **changes):
    args = dict(wall_ns=50, cpu_ns=30, **work())
    return b.debit(phase, **{**args, **changes})


def rows():
    return [dict(case_id=f"case:{i}", arm=arm, source_group=f"source:{i}", split="test",
                 source_id="full-reader-verifier-critic-native-receipt", success=i == 0,
                 qualified=True, formula_flops=10 + j, wall_ns=50 + j, cpu_ns=30 + j,
                 native_child_cpu_ns=5, formula_source="operator_formula_complete.v1")
            for i in range(2) for j, arm in enumerate(("static", "fixed", "gate", "ndu"))]


def frontier(observations, **changes):
    args = dict(arms=["static", "fixed", "gate", "ndu"], metric="formula_flops", edges=[0, 20, 40])
    bins = freeze_frontier_bins(observations=observations, **{**args, **changes})
    return summarize_work_frontier(observations, bins, preregistered_protocol_id=bins["protocol_id"])


class ReaderBudgetTests(unittest.TestCase):
    def test_measured_callback_overrun_debits_before_failure(self):
        b = budget()
        with patch("reader_budget.time.perf_counter_ns", side_effect=[100, 250]), \
                patch("reader_budget.time.process_time_ns", side_effect=[10, 60]):
            with self.assertRaises(BudgetExceeded):
                b.measure("propose", lambda: "answer", work_receipt=work, increment_step=True)
        report = b.report()
        self.assertEqual((report["wall_ns"], report["cpu_ns"], report["steps"], report["callback_count"]),
                         (150, 50, 1, 1))
        self.assertTrue(report["receipts"][0]["overrun"])
        self.assertFalse(report["qualified"])

    def test_admission_reserves_registered_upper_and_tracks_proposal_depth(self):
        b = budget(max_steps=1, max_formula_flops=25)
        debit(b, increment_step=True)
        self.assertFalse(b.can_start("propose", increment_step=True))
        self.assertFalse(b.can_start("verify"))  # 10 spent + 20 registered upper > 25.
        b = budget(max_steps=1)
        debit(b, increment_step=True)
        debit(b, "verify")
        self.assertEqual((b.report()["steps"], b.report()["callback_count"]), (1, 2))

    def test_native_wall_is_not_charged_twice_and_unknown_child_cpu_unqualifies(self):
        b = budget()
        debit(b, "native", native_subprocess_wall_ns=40, native_child_cpu_ns=None,
              native_source_id="native-subprocess:v1")
        self.assertEqual(b.report()["wall_ns"], 50)
        self.assertIsNone(b.report()["native_child_cpu_ns"])
        self.assertFalse(b.report()["qualified"])

    def test_missing_formula_and_invalid_work_receipt_preserve_measured_cost(self):
        b = budget()
        debit(b, formula_flops=None, formula_source=None)
        self.assertIsNone(b.report()["formula_flops"])
        self.assertFalse(b.can_start("verify"))
        b = budget()
        with patch("reader_budget.time.perf_counter_ns", side_effect=[100, 150]), \
                patch("reader_budget.time.process_time_ns", side_effect=[10, 30]):
            self.assertEqual(b.measure("verify", lambda: 7, work_receipt=lambda: {}), 7)
        self.assertEqual(b.report()["wall_ns"], 50)
        self.assertFalse(b.report()["qualified"])

    def test_callback_failure_is_paid_and_changed_registration_rejected(self):
        b = budget()
        with patch("reader_budget.time.perf_counter_ns", side_effect=[100, 150]), \
                patch("reader_budget.time.process_time_ns", side_effect=[10, 30]):
            with self.assertRaises(ZeroDivisionError):
                b.measure("verify", lambda: 1 / 0, work_receipt=work)
        self.assertEqual(b.report()["callback_count"], 1)
        self.assertTrue(b.report()["receipts"][0]["failed"])
        b.registered_upper["verify"]["wall_ns"] = 1
        with self.assertRaises(ValueError):
            b.can_start("verify")

    def test_shared_physical_cost_conserved_over_observed_logical_uses(self):
        cost = dict(feature_id="feature:1", source_id="encoder:measured", cpu_ns=101,
                    wall_ns=103, formula_flops=107, native_child_cpu_ns=0,
                    formula_source="operator_formula_complete.v1")
        uses = [dict(use_id=f"arm:{i}", feature_id="feature:1", source_id="logical:receipt", observed=True)
                for i in range(4)]
        allocated = allocate_shared_feature_cost(cost, uses)
        for meter in ("cpu_ns", "wall_ns", "formula_flops", "native_child_cpu_ns"):
            self.assertEqual(sum(r[meter] for r in allocated["allocations"].values()), cost[meter])
        self.assertFalse(allocated["counterfactual_savings_claimed"])
        uses[0]["observed"] = False
        with self.assertRaises(ValueError):
            allocate_shared_feature_cost(cost, uses)

    def test_all_registered_arms_paired_same_bin_without_exact_equality_claim(self):
        result = frontier(rows())
        self.assertEqual(result["bins"][0]["cases"], 2)
        self.assertEqual(result["bins"][0]["arms"]["ndu"]["actual_work_sum"], 26)
        self.assertFalse(result["strict_equal_work_established"])
        self.assertFalse(result["selection_authority"])

    def test_frontier_preserves_incomplete_and_different_work_exclusions(self):
        observations = rows()
        observations[0]["formula_flops"] = None
        observations[-1]["formula_flops"] = 25
        result = frontier(observations)
        self.assertEqual(result["excluded"], dict(incomplete_cost=1, invalid_execution=0, missing_arm=0,
                                                 different_bin=1, outside_support=0))

    def test_manifest_bin_source_and_duplicate_checks(self):
        observations = rows()
        bins = freeze_frontier_bins(observations=observations, arms=["static", "fixed", "gate", "ndu"],
                                    metric="formula_flops", edges=[0, 20, 40])
        changed = copy.deepcopy(bins)
        changed["edges"] = [0, 40, 80]
        with self.assertRaises(ValueError):
            summarize_work_frontier(observations, changed, preregistered_protocol_id=bins["protocol_id"])
        observations[0]["source_group"] = "changed:source"
        with self.assertRaises(ValueError):
            summarize_work_frontier(observations, bins, preregistered_protocol_id=bins["protocol_id"])
        observations = rows() + [rows()[0]]
        with self.assertRaises(ValueError):
            frontier(observations)

    def test_cpu_frontier_includes_child_cpu(self):
        result = frontier(rows(), metric="cpu_ns", edges=[0, 34, 100])
        self.assertEqual(result["bins"][1]["arms"]["static"]["actual_work_sum"], 70)

    def test_cpu_matching_accepts_unknown_formula_without_full_cost_claim(self):
        observations = rows()
        for row in observations:
            row.update(formula_flops=None, formula_source=None)
        result = frontier(observations, metric="cpu_ns", edges=[0, 100])
        self.assertEqual(result["bins"][0]["cases"], 2)
        self.assertEqual(result["cost_complete"], dict(formula_flops=False, cpu_ns=True, wall_ns=True))
        self.assertTrue(result["unqualified_full_cost"])
        self.assertEqual(result["unqualified_full_cost_cases"], 2)
        self.assertEqual(frontier(observations)["excluded"]["incomplete_cost"], 2)

    def test_wall_matching_accepts_unknown_child_cpu_but_exposes_incompleteness(self):
        observations = rows()
        for row in observations:
            row["native_child_cpu_ns"] = None
        result = frontier(observations, metric="wall_ns", edges=[0, 100])
        self.assertEqual(result["bins"][0]["cases"], 2)
        self.assertEqual(result["cost_complete"], dict(formula_flops=True, cpu_ns=False, wall_ns=True))
        self.assertTrue(result["unqualified_full_cost"])
        self.assertEqual(result["matched_incomplete_cost_rows"]["cpu_ns"], 8)

    def test_explicit_cost_flags_restrict_matching_and_invalid_execution_excluded(self):
        observations = rows()
        observations[0]["cost_complete"] = dict(formula_flops=True, cpu_ns=False, wall_ns=True)
        result = frontier(observations, metric="cpu_ns", edges=[0, 100])
        self.assertEqual(result["excluded"]["incomplete_cost"], 1)
        observations[0]["qualified"] = False
        result = frontier(observations, metric="wall_ns", edges=[0, 100])
        self.assertEqual(result["excluded"]["invalid_execution"], 1)


if __name__ == "__main__":
    unittest.main()
