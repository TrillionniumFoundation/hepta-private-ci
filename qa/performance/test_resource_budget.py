from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("resource_reference", Path(__file__).with_name("reference.py"))
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

BudgetLedger = MODULE.BudgetLedger
BudgetProfile = MODULE.BudgetProfile
Resources = MODULE.Resources


def resources(cpu: int, memory: int, risk: int = 0) -> Resources:
    return Resources(cpu, memory, 0, 0, 0, risk)


class ResourceBudgetTests(unittest.TestCase):
    def ledger(self) -> BudgetLedger:
        return BudgetLedger(BudgetProfile(resources(100, 1_000, 1_000_000), resources(20, 200, 100_000), 2))

    def test_reservation_is_idempotent_and_conflicts_on_drift(self) -> None:
        ledger = self.ledger()
        self.assertTrue(ledger.reserve("a", resources(20, 100, 100_000)))
        self.assertTrue(ledger.reserve("a", resources(20, 100, 100_000)))
        with self.assertRaisesRegex(ValueError, "conflict"):
            ledger.reserve("a", resources(21, 100, 100_000))

    def test_capacity_and_ceiling_fail_closed(self) -> None:
        ledger = self.ledger()
        self.assertTrue(ledger.reserve("a", resources(40, 300, 300_000)))
        self.assertFalse(ledger.reserve("too-large", resources(60, 600, 700_000)))
        self.assertTrue(ledger.reserve("b", resources(10, 100, 100_000)))
        self.assertFalse(ledger.reserve("c", resources(1, 1, 1)))

    def test_release_never_borrows_essential_floor(self) -> None:
        ledger = self.ledger()
        floor = ledger.profile.essential_floor
        self.assertTrue(ledger.reserve("a", resources(20, 100, 100_000)))
        ledger.release("a")
        self.assertEqual(ledger.used, floor)

    def test_overload_selects_declared_degradation(self) -> None:
        ledger = self.ledger()
        self.assertTrue(ledger.reserve("a", resources(75, 700, 800_000)))
        self.assertEqual(ledger.degradation_mode(), "critical_shed_optional")

    def test_product_source_binds_budget_and_readiness(self) -> None:
        config = (ROOT / "codex-rs/hepta-agentd/src/config.rs").read_text(encoding="utf-8")
        daemon = (ROOT / "codex-rs/hepta-supervisor/src/daemon.rs").read_text(encoding="utf-8")
        self.assertIn("ResourceBudget", config)
        self.assertIn("ResourceBudget::local_default", daemon)
        self.assertNotIn("unbounded_channel", daemon)


if __name__ == "__main__":
    unittest.main()
