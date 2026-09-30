from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from control_engineering_v2 import EngineeringControlProduct, HmacTrustStore
from control_engineering_v2.control_plane import EngineeringError


class EngineeringControlProductReadyTests(unittest.TestCase):
    def test_open_and_reconcile_returns_ready_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            product = EngineeringControlProduct.open_and_reconcile(
                root / "engineering.sqlite3",
                root,
                expected_repository="TrillionniumFoundation/hepta-private-ci",
                trust_store=HmacTrustStore({}),
                now_ns=1_000_000,
            )
            try:
                self.assertTrue(product.ready)
                report = product.startup_recovery_report
                self.assertEqual(report.active_claims, ())
                self.assertEqual(report.awaiting_completion_claims, ())
                self.assertEqual(report.active_capacity_reservations, 0)
            finally:
                product.close()

    def test_legacy_constructor_remains_fail_closed_until_reconciled(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with EngineeringControlProduct(
                root / "engineering.sqlite3",
                root,
                expected_repository="TrillionniumFoundation/hepta-private-ci",
                trust_store=HmacTrustStore({}),
            ) as product:
                self.assertFalse(product.ready)
                with self.assertRaisesRegex(
                    EngineeringError,
                    "product_startup_reconciliation_required",
                ):
                    _ = product.startup_recovery_report
                product.startup_reconcile(now_ns=1_000_000)
                self.assertTrue(product.ready)

    def test_reconciliation_failure_closes_connection_before_return(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            captured: dict[str, object] = {}

            def fail(store, *, now_ns=None):
                captured["connection"] = store.connection
                raise EngineeringError("forced_reconciliation_failure")

            with mock.patch(
                "control_engineering_v2.product_runtime.recover_worker_lifecycle",
                side_effect=fail,
            ):
                with self.assertRaisesRegex(
                    EngineeringError,
                    "forced_reconciliation_failure",
                ):
                    EngineeringControlProduct.open_and_reconcile(
                        root / "engineering.sqlite3",
                        root,
                        expected_repository="TrillionniumFoundation/hepta-private-ci",
                        trust_store=HmacTrustStore({}),
                        now_ns=1_000_000,
                    )
            connection = captured["connection"]
            with self.assertRaises(Exception):
                connection.execute("SELECT 1")


if __name__ == "__main__":
    unittest.main()
