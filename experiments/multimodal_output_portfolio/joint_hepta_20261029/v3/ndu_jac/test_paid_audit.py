"""Adversarial controls for conditional evidence, full fees, and no-update."""

from dataclasses import replace
import math
import unittest

from .paid_audit import PaidAudit, Plan


class PaidAuditTests(unittest.TestCase):
    def test_extreme_finite_controls_reject_and_small_alpha_stays_defined(self):
        with self.assertRaises(ValueError):
            Plan("a"*64, 1.0, (0.0, 1.0), (-1e308, 1e308), beta=1e308)
        audit = PaidAudit(Plan("a"*64, 1.0, (0.0, 1.0), (0.0, 0.0), delta=5e-324))
        for i in range(2):
            audit.pair(str(i), "a"*64, 1.0, 0.0, 0.0, 0.0)
        result = audit.decide()
        self.assertEqual(result["decision"], "no-update")
        self.assertTrue(math.isfinite(result["radius"]))
        self.assertTrue(math.isfinite(result["log_alpha"]))

    def setUp(self):
        self.plan = Plan("a" * 64, 1.0, (0.0, 1.0), (-1.0, 1.0), budget=2.0)

    def fill(self, plan=None, candidate=1.0, fee=0.0):
        audit = PaidAudit(plan or self.plan)
        for i in range(512):
            audit.pair(str(i), audit.plan.target, candidate, 0.0, 0.0, fee)
        return audit

    def test_positive_gain_and_full_cost_reversal(self):
        free = self.fill().decide()
        paid = self.fill(fee=0.002).decide()
        self.assertEqual(free["decision"], "adopt")
        self.assertEqual(paid["decision"], "no-update")
        self.assertAlmostEqual(paid["spent"], 1.024)
        self.assertLessEqual(free["local_gain_lower"], 1.0)

    def test_null_and_bad_candidate_cannot_pass(self):
        self.assertEqual(self.fill(candidate=0.0).decide()["decision"], "no-update")
        reverse = PaidAudit(self.plan)
        for i in range(512):
            reverse.pair(str(i), self.plan.target, 0.0, 1.0, 0.0, 0.0)
        self.assertEqual(reverse.decide()["decision"], "no-update")

    def test_control_variate_independent_reset_term(self):
        p = replace(self.plan, beta=0.3)
        a = PaidAudit(p)
        for i in range(512):
            h = -1.0 if i % 2 else 1.0
            a.pair(f"p{i}", p.target, 1.0, 0.0, h, 0.00001)
            a.reset(f"r{i}", p.target, h, 0.000002)
        d = a.decide()
        self.assertAlmostEqual(d["moment_difference"], math.exp(-1) - 1)
        self.assertAlmostEqual(d["spent"], 512 * 0.000012)
        self.assertEqual(d["decision"], "adopt")

    def test_missing_reset_and_reused_fit_or_pair_reject(self):
        p = replace(self.plan, beta=0.3, fit_ids=("fit",), fit_cost=0.01)
        a = self.fill(p)
        self.assertEqual(a.decide()["reason"], "insufficient_independent_samples")
        a.reset("fit", p.target, 0.0, 0.02)
        self.assertEqual(a.decide()["reason"], "invalid_evidence")
        b = self.fill(p)
        b.reset("0", p.target, 0.0, 0.03)
        self.assertEqual(b.decide()["reason"], "invalid_evidence")
        self.assertAlmostEqual(b.spent, 0.04)

    def test_failed_and_wrong_target_attempts_remain_charged(self):
        for values in ((None, 0.0, "a" * 64), (1.1, 0.0, "a" * 64),
                       (1.0, 0.0, "b" * 64)):
            a = PaidAudit(self.plan)
            a.pair("failure", values[2], values[0], values[1], 0.0, 0.12)
            result = a.decide()
            self.assertEqual(result["reason"], "invalid_evidence")
            self.assertEqual(result["spent"], 0.12)
            self.assertEqual(result["attempts"], 1)

    def test_budget_and_error_penalty_block_adoption(self):
        a = self.fill(replace(self.plan, budget=0.1), fee=0.001)
        self.assertEqual(a.decide()["reason"], "validation_budget_exhausted")
        b = self.fill(replace(self.plan, value_penalty=1.0))
        self.assertEqual(b.decide()["decision"], "no-update")

    def test_prefix_size_spending_allows_adaptive_counts(self):
        a = self.fill(replace(self.plan, comparisons=4))
        first = a.decide()["look_alpha"]
        self.assertEqual(first, a.decide()["look_alpha"])
        self.assertAlmostEqual(first, self.plan.delta / (4 * 512 * 513))
        total = sum(self.plan.delta / (m * (m + 1)) for m in range(1, 1001))
        self.assertLess(total, self.plan.delta)
        self.assertAlmostEqual(total, self.plan.delta * 1000 / 1001)

    def test_invalid_support_and_cost_do_not_silently_clip(self):
        for kwargs in ({"eta": True}, {"x_bounds": (-1000.0, 1.0)},
                       {"x_bounds": (1000.0, 1001.0)}, {"budget": -1.0},
                       {"fit_ids": ("x", "x")}, {"delta": 1.0}):
            with self.assertRaises(ValueError):
                replace(self.plan, **kwargs)
        with self.assertRaises(ValueError):
            PaidAudit(self.plan).pair("p", self.plan.target, 1.0, 0.0, 0.0, -1.0)


if __name__ == "__main__":
    unittest.main()
