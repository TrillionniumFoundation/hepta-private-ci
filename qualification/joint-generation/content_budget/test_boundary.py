"""Hand receipt-state tests. These values are examples, not model measurements."""

import unittest

from content_budget.boundary import BoundaryLedger, METHOD_PHASES, Plan, tail_unit_admission_quote


class BoundaryChecks(unittest.TestCase):
    def plan(self):
        return Plan(10., 12_000_000_000, 4.495378557, 3713763611)

    def complete_example(self):
        ledger = BoundaryLedger(self.plan())
        for slot in range(6):
            ledger.charge_method("train", "hand_example", .1, 1_000_000, slot=slot)
        for phase in sorted(METHOD_PHASES - {"prepare", "train"}):
            ledger.charge_method(phase, "hand_example", .01, 10)
        return ledger

    def test_exact_allocation_and_unit_tail(self):
        plan = self.plan()
        self.assertAlmostEqual(plan.common_CPU + 6 * plan.training_CPU_per_slot
                               + plan.tail_CPU + plan.global_guard_CPU, 10.)
        self.assertLess(tail_unit_admission_quote()["total"], plan.tail_units)

    def test_unaffordable_plan_rejected_before_launch(self):
        with self.assertRaises(ValueError):
            Plan(2., 12_000_000_000, 4.495378557, 3713763611)

    def test_research_never_reopens_or_changes_method(self):
        ledger = self.complete_example()
        before = ledger.seal_method("hand-output-digest")
        ledger.charge_review("posthoc_diagnosis", "hand_example", 100., 100_000)
        self.assertEqual(before, ledger.sealed)
        with self.assertRaises(ValueError):
            ledger.charge_method("train", "late_candidate", .01, 1, slot=1)
        with self.assertRaises(ValueError):
            ledger.charge_review("independent_review", "free_selection", .01, 1, uses_for_method=True)

    def test_unused_architecture_and_incomplete_seal_rejected(self):
        ledger = BoundaryLedger(self.plan(), architectures=("independent",))
        with self.assertRaises(ValueError):
            ledger.charge_method("prepare", "native_compile", .1, 0, architecture="native")
        with self.assertRaises(ValueError):
            ledger.seal_method("hand-output-digest")

    def test_actual_overage_is_retained_as_failure(self):
        ledger = self.complete_example()
        ledger.charge_method("export", "unexpected_actual_cost", 10., 100)
        snapshot = ledger.seal_method("failed-hand-output-digest")
        self.assertFalse(snapshot["resource_eligible"])
        self.assertGreater(snapshot["totals"]["CPU"], 10.)
        self.assertIn("actual_method_cap_exceeded", snapshot["failures"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
