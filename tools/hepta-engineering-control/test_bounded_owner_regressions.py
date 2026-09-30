"""Regression sources, not external acceptance or stored pass receipts.

All behavior uses EngineeringStore/EngineeringControlProduct. HMAC identities
below are isolated test fixtures and confer no production acceptance.
"""
from __future__ import annotations

from dataclasses import replace
import multiprocessing
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from control_engineering_v2 import (
    AuditReadCut,
    AuditVerificationBudget,
    EngineeringCapacity,
    EngineeringControlProduct,
    EngineeringError,
    EngineeringStore,
    EngineeringWorkPackage,
    HmacTrustStore,
    ReviewCapacity,
    WorkerHeartbeatReceipt,
    WorkerProfile,
    WorkerRegistrationReceipt,
    WorkerRegistrationRenewalReceipt,
    WorkerResultReceipt,
    WorkEnvelope,
    claim_assignment,
    heartbeat_claim,
)
from control_engineering_v2.capacity_policy import StoreCapacityMonitor, evaluate_store_capacity
from control_engineering_v2.control_plane import DENIED_AUTHORITIES


NOW = 1_000_000_000


def trust():
    return HmacTrustStore({
        ("engineering_worker_identity", "identity-key"): b"fixture-identity",
        ("worker-a", "worker-key"): b"fixture-worker",
    })


def signed(value):
    return replace(value, signature=trust().sign(value, value.issuer, value.signing_identity))


def renewal(predecessor, *, revision=1, key="worker-key-b", observed=NOW + 1,
            expires=NOW + 10_000_000_000):
    return signed(WorkerRegistrationRenewalReceipt(
        "worker-a", revision, predecessor, key, ("python",), 4, ("src",),
        "engineering_worker_identity", "identity-key", observed, expires,
    ))


def renew_in_process(database, repository, receipt, barrier, output, crash=False):
    try:
        with EngineeringControlProduct(
            database, repository, expected_repository="fixture/repository", trust_store=trust()
        ) as product:
            if barrier is not None:
                barrier.wait(timeout=20)
            result = product.renew_worker_registration(receipt, now_ns=NOW + 10)
            if crash:
                os._exit(0)  # Deliberate response loss after the owner committed.
            output.put(("ok", result))
    except BaseException as error:
        if output is not None:
            output.put(("error", repr(error)))
        else:
            raise


class BoundedOwnerRegressions(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database = self.root / "owner.sqlite3"
        self.product = self.open_product()

    def tearDown(self):
        self.product.close()
        self.temporary.cleanup()

    def open_product(self):
        return EngineeringControlProduct(
            self.database, self.root, expected_repository="fixture/repository", trust_store=trust()
        )

    def reopen(self):
        self.product.close()
        self.product = self.open_product()

    def envelope(self, identity):
        return WorkEnvelope(
            identity, "a" * 40, "b" * 40, "c" * 64, "d" * 64,
            "developer-productivity", ("src",), tuple(sorted(DENIED_AUTHORITIES)),
            4, NOW + 20_000_000_000,
        )

    def issue(self, identity, store=None):
        owner = self.product.store if store is None else store
        return owner.issue_work_envelope(self.envelope(identity), now_ns=NOW)

    def registration(self):
        return self.product.register_worker(signed(WorkerRegistrationReceipt(
            "worker-a", "worker-key", ("python",), 4, ("src",),
            "engineering_worker_identity", "identity-key", NOW - 1,
            NOW + 9_000_000_000,
        )), now_ns=NOW)

    def prepare_claim(self):
        self.registration()
        envelope = self.issue("claim-env")
        self.product.plan_work(
            envelope,
            (EngineeringWorkPackage(
                0, "package-a", (), ("src/package-a",), required_skills=("python",),
                capacity_units=1, ci_units=1, review_roles=("architecture",),
                expected_value_q32=100,
            ),),
            (WorkerProfile("worker-a", ("python",), 4, ("src",)),),
            (), EngineeringCapacity(1, (ReviewCapacity("architecture", 1),)),
            generation_id="generation-a", now_ns=NOW,
        )
        self.product.acquire_lease(
            "lease-a", "claim-env", "worker-a", ("src/package-a",),
            authority_epoch=1, expires_unix_ns=NOW + 8_000_000_000, now_ns=NOW + 1,
        )
        self.product.startup_reconcile(now_ns=NOW + 1)

    def result_receipt(self, claim):
        value = WorkerResultReceipt(
            "worker-a", "worker-key", claim.claim_id, claim.claim_fence,
            claim.revision, "e" * 64, "success", NOW + 4, NOW + 1_000_000_004,
        )
        return replace(value, signature=trust().sign(value, value.worker_id, value.worker_signing_identity))

    def audit_count(self):
        return self.product.store.connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]

    def test_event_budget_rejects_before_payload_fetch(self):
        checkpoint = self.product.create_audit_checkpoint(now_ns=NOW)
        for index in range(3):
            self.issue(f"env-{index}")
        trace = []
        connection = self.product.store.connection
        connection.set_trace_callback(trace.append)
        try:
            with self.assertRaisesRegex(EngineeringError, "event_budget_exceeded"):
                self.product.verify_audit_suffix(checkpoint, budget=AuditVerificationBudget(2))
        finally:
            connection.set_trace_callback(None)
        self.assertFalse(any("SELECT * FROM audit_events" in query for query in trace))
        self.assertTrue(any("LIMIT 3" in query for query in trace))

    def test_byte_budget_rejects_before_payload_fetch(self):
        checkpoint = self.product.create_audit_checkpoint(now_ns=NOW)
        self.issue("env")
        trace = []
        connection = self.product.store.connection
        connection.set_trace_callback(trace.append)
        try:
            with self.assertRaisesRegex(EngineeringError, "payload_budget_exceeded"):
                self.product.verify_audit_suffix(checkpoint, budget=AuditVerificationBudget(2, 1))
        finally:
            connection.set_trace_callback(None)
        self.assertFalse(any("SELECT * FROM audit_events" in query for query in trace))

    def test_page_continuation_ignores_new_appends_after_pinned_cut(self):
        checkpoint = self.product.create_audit_checkpoint(now_ns=NOW)
        for index in range(5):
            self.issue(f"env-{index}")
        page = self.product.verify_audit_suffix_page(checkpoint, budget=AuditVerificationBudget(2))
        self.assertFalse(page.complete)
        through = page.through
        verified = page.verified_events
        self.issue("later-append")
        while not page.complete:
            page = self.product.verify_audit_suffix_page(
                page.next_checkpoint, budget=AuditVerificationBudget(2), through=through,
            )
            self.assertGreater(page.verified_events, 0)
            verified += page.verified_events
        self.assertEqual(verified, 5)
        self.assertEqual(page.next_checkpoint.sequence, through.sequence)
        self.assertEqual(page.next_checkpoint.event_digest, through.event_digest)
        self.assertFalse(page.runtime_authority)
        self.assertFalse(page.merge_authority)

    def test_byte_limited_page_makes_progress_without_silent_complete(self):
        checkpoint = self.product.create_audit_checkpoint(now_ns=NOW)
        self.issue("env-a")
        self.issue("env-b")
        size = self.product.store.connection.execute(
            "SELECT length(payload_json) FROM audit_events ORDER BY sequence LIMIT 1"
        ).fetchone()[0]
        page = self.product.verify_audit_suffix_page(
            checkpoint, budget=AuditVerificationBudget(10, size),
        )
        self.assertEqual(page.verified_events, 1)
        self.assertFalse(page.complete)
        with self.assertRaisesRegex(EngineeringError, "payload_budget_exceeded"):
            self.product.verify_audit_suffix_page(checkpoint, budget=AuditVerificationBudget(10, 1))

    def test_suffix_tampering_is_rejected(self):
        checkpoint = self.product.create_audit_checkpoint(now_ns=NOW)
        self.issue("env")
        connection = self.product.store.connection
        for column, value in (
            ("payload_json", b'{"changed":true}'), ("event_type", "changed"),
            ("previous_digest", "e" * 64), ("event_digest", "f" * 64),
            ("event_id", "f" * 32),
        ):
            with self.subTest(column=column):
                connection.execute("BEGIN")
                try:
                    connection.execute(f"UPDATE audit_events SET {column}=?", (value,))
                    with self.assertRaises(EngineeringError):
                        self.product.verify_audit_suffix(checkpoint)
                finally:
                    connection.rollback()

    def test_noncanonical_payload_is_rejected(self):
        checkpoint = self.product.create_audit_checkpoint(now_ns=NOW)
        self.issue("env")
        connection = self.product.store.connection
        connection.execute("BEGIN")
        try:
            connection.execute("UPDATE audit_events SET payload_json=?", (b'{"x":1,"x":2}',))
            with self.assertRaisesRegex(EngineeringError, "payload_invalid"):
                self.product.verify_audit_suffix(checkpoint)
        finally:
            connection.rollback()

    def test_missing_sequence_and_truncated_cut_are_rejected(self):
        checkpoint = self.product.create_audit_checkpoint(now_ns=NOW)
        for index in range(3):
            self.issue(f"env-{index}")
        cut = self.product.verify_audit_suffix_page(checkpoint).through
        connection = self.product.store.connection
        for removed in (2, 3):
            with self.subTest(removed=removed):
                connection.execute("BEGIN")
                try:
                    connection.execute("DELETE FROM audit_events WHERE sequence=?", (removed,))
                    with self.assertRaises(EngineeringError):
                        self.product.verify_audit_suffix(checkpoint, through=cut)
                finally:
                    connection.rollback()

    def test_unknown_or_backward_cut_rejects(self):
        self.issue("env")
        checkpoint = self.product.create_audit_checkpoint(now_ns=NOW)
        for cut in (AuditReadCut(0, "0" * 64), AuditReadCut(1, "f" * 64)):
            with self.subTest(cut=cut):
                with self.assertRaises(EngineeringError):
                    self.product.verify_audit_suffix(checkpoint, through=cut)

    def test_read_does_not_finish_callers_transaction(self):
        checkpoint = self.product.create_audit_checkpoint(now_ns=NOW)
        connection = self.product.store.connection
        connection.execute("BEGIN")
        try:
            self.issue("rolled-back")
            self.assertEqual(self.product.verify_audit_suffix(checkpoint)["verifiedSuffixEvents"], 1)
            self.assertTrue(connection.in_transaction)
        finally:
            connection.rollback()
        self.assertEqual(self.audit_count(), 0)

    def test_invalid_budgets_and_boolean_schema_reject(self):
        for events, size in ((0, 1), (True, 1), (65537, 1), (1, 0), (1, True), (1, 2**27)):
            with self.subTest(events=events, size=size):
                with self.assertRaises(EngineeringError):
                    AuditVerificationBudget(events, size)
        checkpoint = self.product.create_audit_checkpoint(now_ns=NOW)
        with self.assertRaises(EngineeringError):
            self.product.verify_audit_suffix(replace(checkpoint, schema_version=True))

    def test_incremental_reads_do_not_rescan_history(self):
        self.product.capacity_state()
        self.issue("env")
        trace = []
        connection = self.product.store.connection
        connection.set_trace_callback(trace.append)
        try:
            observed = self.product.capacity_state()
            self.assertEqual(self.product.capacity_state()["auditEvents"], 1)
        finally:
            connection.set_trace_callback(None)
        self.assertEqual(observed["auditEvents"], 1)
        self.assertEqual(observed["capacityScope"], "owner_database")
        self.assertFalse(any("COUNT(" in query.upper() for query in trace))
        self.assertFalse(observed["productionAccepted"])

    def test_other_connection_commit_invalidates_counts(self):
        self.assertEqual(self.product.capacity_state()["auditEvents"], 0)
        with EngineeringStore(self.database) as external:
            self.issue("external", external)
        self.assertEqual(self.product.capacity_state()["auditEvents"], 1)
        self.assertEqual(self.product.capacity_state(calibrate=True)["auditEvents"], 1)

    def test_rollback_restores_incremental_counts(self):
        connection = self.product.store.connection
        connection.execute("BEGIN")
        try:
            self.issue("temporary")
            self.assertEqual(self.product.capacity_state()["auditEvents"], 1)
            self.assertTrue(connection.in_transaction)
        finally:
            connection.rollback()
        self.assertEqual(self.product.capacity_state()["auditEvents"], 0)

    def test_counter_calibration_quarantines_drift(self):
        connection = self.product.store.connection
        connection.execute("UPDATE _ce_capacity_counts SET audit_events=audit_events+1")
        connection.commit()
        with self.assertRaisesRegex(EngineeringError, "capacity_projection_drift"):
            self.product.capacity_state(calibrate=True)
        with self.assertRaisesRegex(EngineeringError, "capacity_projection_quarantined"):
            self.product.capacity_state()
        self.assertEqual(self.audit_count(), 0)

    def test_monitor_cannot_be_reused_for_another_owner(self):
        with EngineeringStore(self.root / "other.sqlite3") as other:
            monitor = StoreCapacityMonitor(other)
            with self.assertRaisesRegex(EngineeringError, "owner_mismatch"):
                evaluate_store_capacity(self.product.store, monitor=monitor)

    def test_product_reopen_rebuilds_only_derived_counts(self):
        self.issue("env")
        original_anchor = self.product.audit_anchor()
        self.reopen()
        self.assertEqual(self.product.audit_anchor(), original_anchor)
        self.assertEqual(self.product.capacity_state(calibrate=True)["auditEvents"], 1)
        self.assertIsNone(self.product.store.connection.execute(
            "SELECT name FROM sqlite_master WHERE name='_ce_capacity_counts'"
        ).fetchone())

    def test_foreign_claim_can_settle_before_capacity_refresh(self):
        self.prepare_claim()
        self.assertEqual(self.product.capacity_state()["activeClaims"], 0)
        with EngineeringStore(self.database) as external:
            claim = claim_assignment(
                external, "generation-a", "package-a", "worker-a", "lease-a",
                heartbeat_ttl_ns=1_000_000_000, now_ns=NOW + 2,
            )
            heartbeat = WorkerHeartbeatReceipt(
                "worker-a", "worker-key", claim.claim_id, claim.claim_fence,
                claim.revision, NOW + 3, NOW + 1_000_000_003,
            )
            heartbeat = replace(heartbeat, signature=trust().sign(
                heartbeat, heartbeat.worker_id, heartbeat.worker_signing_identity,
            ))
            claim = heartbeat_claim(
                external, heartbeat, trust(), heartbeat_ttl_ns=1_000_000_000,
                now_ns=NOW + 3,
            )
        # Do not refresh the local projection before settling a foreign claim.
        submitted = self.product.submit_result(self.result_receipt(claim), now_ns=NOW + 4)
        self.assertEqual(submitted.state, "result_submitted")
        self.assertEqual(self.product.capacity_state(calibrate=True)["activeClaims"], 0)
        self.assertEqual(self.product.capacity_state()["auditEvents"], self.audit_count())

    def test_renewal_exact_replay_survives_expiry_and_reopen(self):
        receipt = renewal(self.registration())
        result = self.product.renew_worker_registration(receipt, now_ns=NOW + 1)
        anchor = self.product.audit_anchor()
        self.reopen()
        self.assertEqual(self.product.renew_worker_registration(
            receipt, now_ns=receipt.expires_unix_ns + 1,
        ), result)
        self.assertEqual(self.product.audit_anchor(), anchor)
        row = self.product.store.connection.execute(
            "SELECT revision,expires_unix_ns FROM worker_registrations"
        ).fetchone()
        self.assertEqual(tuple(row), (2, receipt.expires_unix_ns))

    def test_same_profile_different_receipt_is_not_a_replay(self):
        receipt = renewal(self.registration())
        self.product.renew_worker_registration(receipt, now_ns=NOW + 1)
        anchor = self.product.audit_anchor()
        drifted = signed(replace(receipt, observed_unix_ns=NOW + 2, signature=""))
        with self.assertRaisesRegex(EngineeringError, "identity_conflict"):
            self.product.renew_worker_registration(drifted, now_ns=NOW + 2)
        self.assertEqual(self.product.audit_anchor(), anchor)

    def test_replay_rechecks_signature_and_revocation(self):
        receipt = renewal(self.registration())
        self.product.renew_worker_registration(receipt, now_ns=NOW + 1)
        with self.assertRaisesRegex(EngineeringError, "signature"):
            self.product.renew_worker_registration(replace(receipt, signature="invalid"), now_ns=NOW + 2)
        connection = self.product.store.connection
        connection.execute("BEGIN")
        try:
            connection.execute("UPDATE worker_registrations SET state='revoked'")
            with self.assertRaisesRegex(EngineeringError, "worker_not_active"):
                self.product.renew_worker_registration(receipt, now_ns=NOW + 2)
        finally:
            connection.rollback()

    def test_historical_replay_does_not_undo_a_later_renewal(self):
        first = renewal(self.registration())
        original = self.product.renew_worker_registration(first, now_ns=NOW + 1)
        second = renewal(original, revision=2, key="worker-key-c", observed=NOW + 2,
                         expires=NOW + 11_000_000_000)
        self.product.renew_worker_registration(second, now_ns=NOW + 2)
        anchor = self.product.audit_anchor()
        self.assertEqual(self.product.renew_worker_registration(first, now_ns=NOW + 3), original)
        self.assertEqual(self.product.audit_anchor(), anchor)
        row = self.product.store.connection.execute(
            "SELECT revision,worker_signing_identity FROM worker_registrations"
        ).fetchone()
        self.assertEqual(tuple(row), (3, "worker-key-c"))

    def test_key_rotation_with_reserved_claim_rejects(self):
        self.prepare_claim()
        self.product.claim("generation-a", "package-a", "worker-a", "lease-a",
                           heartbeat_ttl_ns=1_000_000_000, now_ns=NOW + 2)
        predecessor = self.product.store.connection.execute(
            "SELECT profile_digest FROM worker_registrations"
        ).fetchone()[0]
        with self.assertRaisesRegex(EngineeringError, "rotation_with_active_claims"):
            self.product.renew_worker_registration(renewal(predecessor), now_ns=NOW + 3)
        self.assertEqual(self.product.capacity_state()["activeClaims"], 1)

    def test_audit_failure_rolls_back_renewal_inside_caught_outer_transaction(self):
        receipt = renewal(self.registration())
        connection = self.product.store.connection
        anchor = self.product.audit_anchor()
        def deny_audit_insert(action, table, _column, _database, _trigger):
            return sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_INSERT and table == "audit_events" else sqlite3.SQLITE_OK
        connection.execute("BEGIN")
        connection.set_authorizer(deny_audit_insert)
        try:
            with self.assertRaises(sqlite3.DatabaseError):
                self.product.renew_worker_registration(receipt, now_ns=NOW + 1)
        finally:
            connection.set_authorizer(None)
        self.assertTrue(connection.in_transaction)
        connection.commit()
        self.assertEqual(connection.execute("SELECT revision FROM worker_registrations").fetchone()[0], 1)
        self.assertEqual(self.product.audit_anchor(), anchor)

    def test_two_process_identical_renewals_commit_once(self):
        receipt = renewal(self.registration())
        before = self.audit_count()
        context = multiprocessing.get_context("spawn")
        barrier, output = context.Barrier(2), context.Queue()
        processes = [context.Process(target=renew_in_process, args=(
            str(self.database), str(self.root), receipt, barrier, output,
        )) for _ in range(2)]
        try:
            for process in processes:
                process.start()
            for process in processes:
                process.join(timeout=30)
                self.assertEqual(process.exitcode, 0)
            results = [output.get(timeout=5) for _ in processes]
            self.assertEqual([result[0] for result in results], ["ok", "ok"], results)
            self.assertEqual(results[0][1], results[1][1])
            self.assertEqual(self.audit_count(), before + 1)
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)
            output.close()

    def test_process_exit_after_commit_recovers_original_result(self):
        receipt = renewal(self.registration())
        before = self.audit_count()
        context = multiprocessing.get_context("spawn")
        process = context.Process(target=renew_in_process, args=(
            str(self.database), str(self.root), receipt, None, None, True,
        ))
        try:
            process.start()
            process.join(timeout=30)
            self.assertEqual(process.exitcode, 0)
            self.reopen()
            anchor = self.product.audit_anchor()
            self.product.renew_worker_registration(receipt, now_ns=NOW + 11)
            self.assertEqual(self.audit_count(), before + 1)
            self.assertEqual(self.product.audit_anchor(), anchor)
        finally:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
