"""Behavioral checks for common-budget admission, restart and concurrency."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest

from budget_ledger import BudgetExceeded, BudgetLedger, GAUGES, METERS, digest


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "budget.sqlite3"
        self.arguments = dict(
            arm="single",
            protocol_sha256="a" * 64,
            limits={k: 10 for k in METERS},
            gauges={k: 100 for k in GAUGES},
            prices={k: 1 for k in METERS},
            cost_limit=20,
        )
        self.ledger = BudgetLedger(self.path, **self.arguments)

    def reserve(self, name, values):
        return self.ledger.reserve(
            name, "infer", values, request_sha256=digest([name, values])
        )

    def test_reserved_work_survives_restart_and_cannot_be_oversubscribed(self):
        self.reserve("first", {"cpu_ns": 8})
        other = BudgetLedger(self.path, **self.arguments)
        with self.assertRaises(BudgetExceeded):
            other.reserve("second", "infer", {"cpu_ns": 3}, request_sha256="b" * 64)
        self.assertEqual(other.snapshot()["pending"]["cpu_ns"], 8)
        other.settle("first", {"cpu_ns": 6}, receipt_sha256="c" * 64)
        self.reserve("second", {"cpu_ns": 4})
        self.assertEqual(self.ledger.snapshot()["used"]["cpu_ns"], 6)

    def test_global_cost_and_all_workload_dimensions_apply(self):
        self.reserve("cost", {"cpu_ns": 10, "wall_ns": 10})
        with self.assertRaises(BudgetExceeded):
            self.reserve("extra", {"read_bytes": 1})
        with self.assertRaises(ValueError):
            self.reserve("invented", {"unmetered": 1})
        with self.assertRaises(ValueError):
            self.reserve("bool", {"decoder_queries": True})

    def test_only_one_concurrent_competing_reservation_is_admitted(self):
        def claim(name):
            try:
                self.reserve(name, {"decoder_queries": 7})
                return "admitted"
            except BudgetExceeded:
                return "denied"

        with ThreadPoolExecutor(max_workers=2) as pool:
            result = sorted(pool.map(claim, ["one", "two"]))
        self.assertEqual(result, ["admitted", "denied"])

    def test_overrun_is_durable_and_cannot_be_hidden_by_retry(self):
        self.reserve("call", {"cpu_ns": 4})
        with self.assertRaises(BudgetExceeded):
            self.ledger.settle("call", {"cpu_ns": 5}, receipt_sha256="d" * 64)
        state = BudgetLedger(self.path, **self.arguments).snapshot()
        self.assertEqual((state["closed"], state["used"]["cpu_ns"]), (True, 5))
        with self.assertRaises(BudgetExceeded):
            self.reserve("after", {})
        with self.assertRaises(ValueError):
            self.ledger.settle("call", {"cpu_ns": 4}, receipt_sha256="d" * 64)

    def test_identical_settlement_is_idempotent_and_loss_never_refunds(self):
        reservation = self.reserve("call", {"cpu_ns": 4})
        self.assertEqual(self.reserve("call", {"cpu_ns": 4}), reservation)
        first = self.ledger.settle("call", {"cpu_ns": 3}, receipt_sha256="e" * 64)
        self.assertEqual(
            self.ledger.settle("call", {"cpu_ns": 3}, receipt_sha256="e" * 64), first
        )
        self.reserve("crashed", {"cpu_ns": 6})
        self.ledger.abandon(
            "crashed", reason="worker disappeared without a terminal measurement"
        )
        state = self.ledger.snapshot()
        self.assertEqual((state["used"]["cpu_ns"], state["closed"]), (9, True))

    def test_complete_inventory_and_identity_are_admission_boundaries(self):
        self.ledger.observe_inventory(
            {"retained_bytes": 90, "private_bytes": 50, "peak_rss_bytes": 70},
            inventory_sha256="f" * 64,
        )
        with self.assertRaises(BudgetExceeded):
            self.ledger.observe_inventory(
                {"retained_bytes": 101, "private_bytes": 50, "peak_rss_bytes": 60},
                inventory_sha256="1" * 64,
            )
        state = self.ledger.snapshot()
        self.assertTrue(state["closed"])
        self.assertEqual(state["inventory"]["gauges"]["peak_rss_bytes"], 70)
        changed = dict(self.arguments, cost_limit=21)
        with self.assertRaises(ValueError):
            BudgetLedger(self.path, **changed)

    def test_shared_allocation_consumes_ceiling_without_fabricating_execution(self):
        self.ledger.reserve(
            "shared",
            "train",
            {"cpu_ns": 8},
            request_sha256="3" * 64,
            cost_origin="allocated_shared",
            shared_receipt_sha256="4" * 64,
        )
        with self.assertRaises(ValueError):
            self.ledger.settle("shared", {"cpu_ns": 8}, receipt_sha256="5" * 64)
        self.ledger.settle("shared", {"cpu_ns": 8}, receipt_sha256="4" * 64)
        state = self.ledger.snapshot()
        self.assertEqual(
            (
                state["used"]["cpu_ns"],
                state["executed_used"]["cpu_ns"],
                state["allocated_dependency_used"]["cpu_ns"],
            ),
            (8, 0, 8),
        )
        with self.assertRaises(BudgetExceeded):
            self.reserve("marginal", {"cpu_ns": 3})


if __name__ == "__main__":
    unittest.main()
