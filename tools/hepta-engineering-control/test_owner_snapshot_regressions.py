"""Snapshot and read-budget regressions through the normal product and owner.

Trace callbacks below schedule real writes on a separate SQLite owner; they do
not substitute a different execution path or loosen the product's permissions.
"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from control_engineering_v2 import (
    AuditVerificationBudget,
    EngineeringControlProduct,
    EngineeringError,
    EngineeringStore,
    HmacTrustStore,
    WorkEnvelope,
)
from control_engineering_v2.control_plane import DENIED_AUTHORITIES


NOW = 1_000_000_000


class OwnerSnapshotRegressions(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.product = EngineeringControlProduct(
            self.root / "owner.sqlite3", self.root,
            expected_repository="fixture/repository", trust_store=HmacTrustStore({}),
        )
        self.addCleanup(self.product.close)

    def issue(self, identity: str, store: EngineeringStore | None = None) -> None:
        owner = self.product.store if store is None else store
        envelope = WorkEnvelope(
            identity, "a" * 40, "b" * 40, "c" * 64, "d" * 64,
            "developer-productivity", ("src",), tuple(sorted(DENIED_AUTHORITIES)),
            4, NOW + 20_000_000_000,
        )
        owner.issue_work_envelope(envelope, now_ns=NOW)

    def test_foreign_commit_between_version_and_snapshot_does_not_quarantine(self) -> None:
        self.assertEqual(self.product.capacity_state()["auditEvents"], 0)
        connection = self.product.store.connection
        fired = []
        errors = []
        with EngineeringStore(self.root / "owner.sqlite3") as external:
            def inject(query: str) -> None:
                if query.startswith("SELECT sequence FROM main.audit_events LIMIT 1") and not fired:
                    fired.append(True)
                    try:
                        self.issue("foreign-before-pin", external)
                    except Exception as error:
                        errors.append(error)
            connection.set_trace_callback(inject)
            try:
                observed = self.product.capacity_state(calibrate=True)
            finally:
                connection.set_trace_callback(None)
        self.assertEqual(fired, [True])
        self.assertEqual(errors, [])
        self.assertEqual(observed["auditEvents"], 1)
        self.assertEqual(self.product.capacity_state(calibrate=True)["auditEvents"], 1)
        self.assertFalse(connection.in_transaction)
        self.assertFalse(observed["productionAccepted"])

    def test_foreign_commit_after_pin_is_retried_without_stale_counts(self) -> None:
        connection = self.product.store.connection
        fired = []
        errors = []
        with EngineeringStore(self.root / "owner.sqlite3") as external:
            def inject(query: str) -> None:
                if query.startswith("SELECT audit_events,active_claims FROM _ce_capacity_counts") and not fired:
                    fired.append(True)
                    try:
                        self.issue("foreign-after-pin", external)
                    except Exception as error:
                        errors.append(error)
            connection.set_trace_callback(inject)
            try:
                observed = self.product.capacity_state(calibrate=True)
            finally:
                connection.set_trace_callback(None)
        self.assertEqual(errors, [])
        self.assertEqual(fired, [True])
        self.assertEqual(observed["auditEvents"], 1)

    def test_continuous_pre_pin_churn_is_bounded_not_permanent_quarantine(self) -> None:
        connection = self.product.store.connection
        fired = []
        errors = []
        with EngineeringStore(self.root / "owner.sqlite3") as external:
            def inject(query: str) -> None:
                if query.startswith("SELECT sequence FROM main.audit_events LIMIT 1"):
                    fired.append(len(fired))
                    try:
                        self.issue(f"foreign-churn-{len(fired)}", external)
                    except Exception as error:
                        errors.append(error)
            connection.set_trace_callback(inject)
            try:
                with self.assertRaisesRegex(EngineeringError, "capacity_observation_changed"):
                    self.product.capacity_state(calibrate=True)
            finally:
                connection.set_trace_callback(None)
        self.assertEqual(errors, [])
        self.assertEqual(len(fired), 3)
        self.assertFalse(connection.in_transaction)
        self.assertEqual(self.product.capacity_state(calibrate=True)["auditEvents"], 3)

    def test_fractional_counter_is_rejected_without_integer_coercion(self) -> None:
        connection = self.product.store.connection
        connection.execute("UPDATE _ce_capacity_counts SET audit_events=0.5")
        connection.commit()
        with self.assertRaisesRegex(EngineeringError, "capacity_projection_invalid"):
            self.product.capacity_state(calibrate=True)
        with self.assertRaisesRegex(EngineeringError, "capacity_projection_quarantined"):
            self.product.capacity_state()

    def test_text_counter_is_rejected_as_typed_failure(self) -> None:
        connection = self.product.store.connection
        connection.execute("UPDATE _ce_capacity_counts SET active_claims='invalid'")
        connection.commit()
        with self.assertRaisesRegex(EngineeringError, "capacity_projection_invalid"):
            self.product.capacity_state()

    def test_missing_projection_latches_quarantine(self) -> None:
        connection = self.product.store.connection
        connection.execute("DELETE FROM _ce_capacity_counts")
        connection.commit()
        with self.assertRaisesRegex(EngineeringError, "capacity_projection_missing"):
            self.product.capacity_state()
        with self.assertRaisesRegex(EngineeringError, "capacity_projection_quarantined"):
            self.product.capacity_state()

    def assert_metadata_rejected_before_payload(self, column: str, value: object) -> None:
        checkpoint = self.product.create_audit_checkpoint(now_ns=NOW)
        self.issue("metadata-event")
        # Column names are fixed test literals, never external SQL input.
        self.assertIn(column, {"event_id", "previous_digest", "created_unix_ns", "payload_json"})
        connection = self.product.store.connection
        connection.execute("BEGIN")
        connection.execute(f"UPDATE audit_events SET {column}=?", (value,))
        trace = []
        connection.set_trace_callback(trace.append)
        try:
            with self.assertRaisesRegex(EngineeringError, "audit_chain_metadata_invalid"):
                self.product.verify_audit_suffix(checkpoint)
            self.assertTrue(connection.in_transaction)
        finally:
            connection.set_trace_callback(None)
            connection.rollback()
        self.assertFalse(any(query.startswith("SELECT * FROM audit_events") for query in trace))

    def test_nul_tailed_identifier_cannot_bypass_metadata_byte_budget(self) -> None:
        self.assert_metadata_rejected_before_payload("event_id", "f" * 32 + "\x00" + "x" * 131072)

    def test_nul_tailed_predecessor_cannot_bypass_metadata_byte_budget(self) -> None:
        self.assert_metadata_rejected_before_payload("previous_digest", "0" * 64 + "\x00" + "x" * 131072)

    def test_noninteger_timestamp_rejects_before_payload_read(self) -> None:
        self.assert_metadata_rejected_before_payload("created_unix_ns", NOW + 0.5)

    def test_text_payload_rejects_before_payload_read(self) -> None:
        self.assert_metadata_rejected_before_payload("payload_json", '{"value":1}')

    def test_large_json_integer_is_a_typed_failure_and_preserves_outer_transaction(self) -> None:
        checkpoint = self.product.create_audit_checkpoint(now_ns=NOW)
        self.issue("large-integer")
        connection = self.product.store.connection
        connection.execute("BEGIN")
        connection.execute("UPDATE audit_events SET payload_json=?", (b'{"x":' + b'1' * 10000 + b'}',))
        try:
            with self.assertRaises(EngineeringError):
                self.product.verify_audit_suffix(checkpoint)
            self.assertTrue(connection.in_transaction)
        finally:
            connection.rollback()

    def test_admitted_page_streams_one_bounded_payload_query(self) -> None:
        checkpoint = self.product.create_audit_checkpoint(now_ns=NOW)
        for index in range(5):
            self.issue(f"page-{index}")
        connection = self.product.store.connection
        trace = []
        connection.set_trace_callback(trace.append)
        try:
            page = self.product.verify_audit_suffix_page(checkpoint, budget=AuditVerificationBudget(3))
        finally:
            connection.set_trace_callback(None)
        reads = [query for query in trace if query.startswith("SELECT * FROM audit_events")]
        self.assertEqual(len(reads), 1)
        self.assertIn("LIMIT 3", reads[0])
        self.assertEqual(page.verified_events, 3)
        self.assertFalse(page.complete)
        self.issue("append-after-cut")
        remainder = self.product.verify_audit_suffix_page(
            page.next_checkpoint, budget=AuditVerificationBudget(3), through=page.through,
        )
        self.assertTrue(remainder.complete)
        self.assertEqual(remainder.verified_events, 2)
        self.assertFalse(remainder.runtime_authority)
        self.assertFalse(remainder.merge_authority)


if __name__ == "__main__":
    unittest.main()
