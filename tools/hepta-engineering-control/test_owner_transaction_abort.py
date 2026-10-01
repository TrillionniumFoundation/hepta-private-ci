"""Real SQLite automatic rollback must not permit nested owner commits."""

from dataclasses import replace
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from control_engineering_v2 import (
    EngineeringError, EngineeringStore, HmacTrustStore, WorkerRegistrationReceipt,
    WorkerRegistrationRenewalReceipt, WorkEnvelope, register_worker,
    renew_worker_registration,
)
from control_engineering_v2.control_plane import DENIED_AUTHORITIES


class OwnerTransactionAbortTests(unittest.TestCase):
    def envelope(self, identity):
        return WorkEnvelope(
            identity, "a" * 40, "b" * 40, "c" * 64, "d" * 64, "owner",
            ("src",), tuple(sorted(DENIED_AUTHORITIES)), 4, 10_000,
        )

    def force_sqlite_full(self, store):
        oversized = replace(
            self.envelope("oversized"),
            allowed_paths=tuple("src/" + str(index) + "x" * 900 for index in range(30)),
        )
        with self.assertRaisesRegex(sqlite3.OperationalError, "database or disk is full"):
            store.issue_work_envelope(oversized, now_ns=2)
        self.assertFalse(store.connection.in_transaction)

    def limit_pages(self, store):
        pages = store.connection.execute("PRAGMA page_count").fetchone()[0]
        store.connection.execute(f"PRAGMA max_page_count={pages}")

    def assert_empty(self, store):
        self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM work_envelopes").fetchone()[0], 0)
        self.assertEqual(store.audit_anchor()["sequence"], 0)

    def test_caught_sqlite_full_blocks_continuation_and_outer_commit_then_recovers(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "owner.sqlite3"
            with EngineeringStore(database) as store:
                self.limit_pages(store)
                with self.assertRaisesRegex(EngineeringError, "owner_transaction_aborted"):
                    with store._transaction():
                        store.issue_work_envelope(self.envelope("before"), now_ns=1)
                        self.force_sqlite_full(store)
                        with self.assertRaisesRegex(EngineeringError, "owner_transaction_aborted"):
                            store.issue_work_envelope(self.envelope("escaped"), now_ns=3)
                self.assert_empty(store)
                store.issue_work_envelope(self.envelope("next-request"), now_ns=4)
            with EngineeringStore(database) as reopened:
                self.assertEqual(
                    tuple(row[0] for row in reopened.connection.execute("SELECT envelope_id FROM work_envelopes")),
                    ("next-request",),
                )
                reopened.verify_audit_chain()

    def test_caught_sqlite_full_cannot_leave_silent_success_without_more_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "owner.sqlite3"
            with EngineeringStore(database) as store:
                self.limit_pages(store)
                with self.assertRaisesRegex(EngineeringError, "owner_transaction_aborted"):
                    with store._transaction():
                        store.issue_work_envelope(self.envelope("before"), now_ns=1)
                        self.force_sqlite_full(store)
                self.assert_empty(store)
            with EngineeringStore(database) as reopened:
                self.assert_empty(reopened)

    def test_outer_exception_after_caught_sqlite_full_keeps_all_writes_rolled_back(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "owner.sqlite3"
            with EngineeringStore(database) as store:
                self.limit_pages(store)
                with self.assertRaisesRegex(RuntimeError, "outer abort"):
                    with store._transaction():
                        store.issue_work_envelope(self.envelope("before"), now_ns=1)
                        self.force_sqlite_full(store)
                        with self.assertRaisesRegex(EngineeringError, "owner_transaction_aborted"):
                            store.issue_work_envelope(self.envelope("escaped"), now_ns=3)
                        raise RuntimeError("outer abort")
                self.assert_empty(store)
            with EngineeringStore(database) as reopened:
                self.assert_empty(reopened)

    def signed_registration(self, trust, paths=("src",)):
        receipt = WorkerRegistrationReceipt(
            "worker", "worker-key", ("python",), 4, paths,
            "engineering_worker_identity", "identity-key", 1, 10_000,
        )
        return replace(receipt, signature=trust.sign(receipt, receipt.issuer, receipt.signing_identity))

    def test_registration_sqlite_full_preserves_original_failure_and_recovers(self):
        trust = HmacTrustStore({("engineering_worker_identity", "identity-key"): b"fixture"})
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "owner.sqlite3"
            with EngineeringStore(database) as store:
                self.limit_pages(store)
                huge = self.signed_registration(
                    trust, tuple("src/" + str(index) + "x" * 900 for index in range(30)),
                )
                with self.assertRaisesRegex(EngineeringError, "owner_transaction_aborted"):
                    with store._transaction():
                        store.issue_work_envelope(self.envelope("before"), now_ns=1)
                        with self.assertRaisesRegex(sqlite3.OperationalError, "database or disk is full"):
                            register_worker(store, huge, trust, now_ns=2)
                        with self.assertRaisesRegex(EngineeringError, "owner_transaction_aborted"):
                            register_worker(store, self.signed_registration(trust), trust, now_ns=3)
                self.assert_empty(store)
                digest = register_worker(store, self.signed_registration(trust), trust, now_ns=4)
            with EngineeringStore(database) as reopened:
                row = reopened.connection.execute("SELECT profile_digest,revision FROM worker_registrations").fetchone()
                self.assertEqual(tuple(row), (digest, 1))

    def test_renewal_sqlite_full_keeps_predecessor_and_next_request_can_renew(self):
        trust = HmacTrustStore({("engineering_worker_identity", "identity-key"): b"fixture"})
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "owner.sqlite3"
            with EngineeringStore(database) as store:
                predecessor = register_worker(store, self.signed_registration(trust), trust, now_ns=1)
                anchor = store.audit_anchor()
                self.limit_pages(store)
                receipt = WorkerRegistrationRenewalReceipt(
                    "worker", 1, predecessor, "worker-key", ("python",), 4,
                    tuple("src/" + str(index) + "x" * 900 for index in range(30)),
                    "engineering_worker_identity", "identity-key", 2, 11_000,
                )
                receipt = replace(receipt, signature=trust.sign(receipt, receipt.issuer, receipt.signing_identity))
                with self.assertRaisesRegex(EngineeringError, "owner_transaction_aborted"):
                    with store._transaction():
                        store.issue_work_envelope(self.envelope("before"), now_ns=2)
                        with self.assertRaisesRegex(sqlite3.OperationalError, "database or disk is full"):
                            renew_worker_registration(store, receipt, trust, now_ns=3)
                        with self.assertRaisesRegex(EngineeringError, "owner_transaction_aborted"):
                            store.issue_work_envelope(self.envelope("escaped"), now_ns=4)
                self.assertEqual(store.audit_anchor(), anchor)
                self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM work_envelopes").fetchone()[0], 0)
                row = store.connection.execute("SELECT profile_digest,revision FROM worker_registrations").fetchone()
                self.assertEqual(tuple(row), (predecessor, 1))
                valid = replace(receipt, allowed_paths=("src",), capacity_units=5, signature="")
                valid = replace(valid, signature=trust.sign(valid, valid.issuer, valid.signing_identity))
                result = renew_worker_registration(store, valid, trust, now_ns=5)
            with EngineeringStore(database) as reopened:
                row = reopened.connection.execute("SELECT profile_digest,revision FROM worker_registrations").fetchone()
                self.assertEqual(tuple(row), (result, 2))

    def test_failed_savepoint_cleanup_disposes_owner_and_preserves_original_error(self):
        def deny_savepoint_rollback(action, operation, _name, _database, _trigger):
            if action == sqlite3.SQLITE_SAVEPOINT and operation == "ROLLBACK":
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "owner.sqlite3"
            with EngineeringStore(database) as store:
                with self.assertRaisesRegex(EngineeringError, "owner_transaction_unrecoverable"):
                    with store._transaction():
                        store.connection.set_authorizer(deny_savepoint_rollback)
                        with patch.object(store, "_append_audit", side_effect=OSError("original audit failure")):
                            with self.assertRaisesRegex(OSError, "original audit failure") as failure:
                                store.issue_work_envelope(self.envelope("partial"), now_ns=1)
                        self.assertTrue(any("rollback failed" in note for note in failure.exception.__notes__))
                        with self.assertRaisesRegex(EngineeringError, "owner_transaction_unrecoverable"):
                            store.issue_work_envelope(self.envelope("escaped"), now_ns=2)
                with self.assertRaisesRegex(EngineeringError, "owner_transaction_unrecoverable"):
                    store.issue_work_envelope(self.envelope("next-request"), now_ns=3)
            with EngineeringStore(database) as reopened:
                self.assert_empty(reopened)
                reopened.issue_work_envelope(self.envelope("fresh-owner"), now_ns=4)


class SchemaLiteralIntegrityTests(unittest.TestCase):
    def change_declaration(self, database, before, after):
        with sqlite3.connect(database) as connection:
            connection.execute("PRAGMA writable_schema=ON")
            connection.execute(
                "UPDATE sqlite_master SET sql=replace(sql,?,?) WHERE name='path_leases'",
                (before, after),
            )

    def test_literal_case_change_in_check_constraint_is_rejected_on_reopen(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "owner.sqlite3"
            with EngineeringStore(database):
                pass
            self.change_declaration(database, "'active'", "'ACTIVE'")
            with self.assertRaisesRegex(EngineeringError, "store_schema_definition_mismatch"):
                EngineeringStore(database)

    def test_keyword_case_and_token_whitespace_remain_compatible(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "owner.sqlite3"
            with EngineeringStore(database):
                pass
            self.change_declaration(database, "CREATE TABLE", "create   table")
            self.change_declaration(database, "CHECK(", "check (\n")
            with EngineeringStore(database) as reopened:
                reopened.issue_work_envelope(OwnerTransactionAbortTests().envelope("env"), now_ns=1)
                lease = reopened.acquire_path_lease(
                    "lease", "env", "worker", ("src/file",), authority_epoch=1,
                    expires_unix_ns=100, now_ns=2,
                )
                self.assertEqual(lease.state, "active")


if __name__ == "__main__":
    unittest.main()
