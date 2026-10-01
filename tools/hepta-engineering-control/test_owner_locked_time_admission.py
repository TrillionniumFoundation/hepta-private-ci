"""Owner authority uses the wall-clock cut after SQLite acquires its write lock."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
import sqlite3
import tempfile
from threading import Event
import time
import unittest
from unittest.mock import patch

from control_engineering_v2 import (
    CanonicalSourceReceipt,
    EngineeringCapacity,
    EngineeringError,
    EngineeringStore,
    EngineeringWorkPackage,
    HmacTrustStore,
    WorkerProfile,
    WorkerRegistrationReceipt,
    WorkerRegistrationRenewalReceipt,
    WorkPackage,
    claim_assignment,
    heartbeat_claim,
    issue_signed_work_envelope,
    observe_claim_completion,
    observe_integration_stage,
    plan_engineering_work,
    record_integration_decision,
    submit_worker_result,
)
from control_engineering_v2.integration_controller import reconcile_integration_item
import test_integration_controller as integration_fixtures
import test_lane_g_seal as seal_fixtures
import test_orchestration as orchestration_fixtures
import test_product_claim_admission as product_fixtures
import test_worker_lifecycle as worker_fixtures


class OwnerLockedTimeAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store_sequence = 0

    def fixture(self, fixture_class):
        fixture = fixture_class()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    def store(self):
        self.store_sequence += 1
        store = EngineeringStore(Path(self.temporary.name) / f"owner-{self.store_sequence}.db")
        self.addCleanup(store.close)
        return store

    @contextmanager
    def advance_at_lock(self, store, before, after):
        clock = [before]
        original = store._transaction

        @contextmanager
        def transaction():
            with original():
                clock[0] = after
                yield

        with patch("time.time_ns", side_effect=lambda: clock[0]), patch.object(
            store, "_transaction", transaction
        ):
            yield

    def test_public_claim_real_second_connection_wait_uses_post_lock_time(self):
        for logical_time in (False, True):
            with self.subTest(logical_time=logical_time):
                fixture = self.fixture(product_fixtures.ProductClaimAdmissionTests)
                plan = fixture.plan("job", "src/job")
                fixture.lease()
                store = fixture.product.store
                anchor = store.audit_anchor()
                clock = [fixture.now + 2]
                writer_ready = Event()
                owner_begin = Event()

                def hold_write_lock():
                    with sqlite3.connect(fixture.database) as blocker:
                        blocker.execute("BEGIN IMMEDIATE")
                        writer_ready.set()
                        if not owner_begin.wait(5):
                            raise AssertionError("owner did not attempt BEGIN IMMEDIATE")
                        # Keep the second connection's real write lock held
                        # while the owner is already waiting to acquire it.
                        time.sleep(0.05)
                        clock[0] = fixture.now + 1_000_001
                        blocker.rollback()

                def trace(statement):
                    if statement == "BEGIN IMMEDIATE":
                        owner_begin.set()

                with ThreadPoolExecutor(max_workers=1) as pool:
                    blocker = pool.submit(hold_write_lock)
                    self.assertTrue(writer_ready.wait(5))
                    store.connection.set_trace_callback(trace)
                    try:
                        with patch("time.time_ns", side_effect=lambda: clock[0]):
                            arguments = {"now_ns": fixture.now + 2} if logical_time else {}
                            if logical_time:
                                claim = fixture.product.claim(
                                    plan.generation_id, "job", "worker", "lease",
                                    heartbeat_ttl_ns=100, **arguments,
                                )
                                self.assertEqual(claim.claimed_unix_ns, fixture.now + 2)
                            else:
                                with self.assertRaisesRegex(EngineeringError, "worker_not_active"):
                                    fixture.product.claim(
                                        plan.generation_id, "job", "worker", "lease",
                                        heartbeat_ttl_ns=100,
                                    )
                                self.assertEqual(store.audit_anchor(), anchor)
                                self.assertEqual(fixture.product.worker_capacity("worker").reserved_units, 0)
                    finally:
                        store.connection.set_trace_callback(None)
                    blocker.result(timeout=5)

    def test_public_registration_checks_signed_window_after_lock(self):
        fixture = self.fixture(product_fixtures.ProductClaimAdmissionTests)
        receipt = WorkerRegistrationReceipt(
            "worker-two", "worker-key", ("python",), 4, ("src",),
            "engineering_worker_identity", "identity-key", fixture.now, fixture.now + 10,
        )
        receipt = replace(receipt, signature=fixture.trust.sign(receipt, receipt.issuer, receipt.signing_identity))
        anchor = fixture.product.audit_anchor()
        with self.advance_at_lock(fixture.product.store, fixture.now + 2, fixture.now + 20):
            with self.assertRaisesRegex(EngineeringError, "worker_registration_stale"):
                fixture.product.register_worker(receipt)
            self.assertEqual(fixture.product.audit_anchor(), anchor)
            fixture.product.register_worker(receipt, now_ns=fixture.now + 2)
        self.assertEqual(fixture.product.store.connection.execute(
            "SELECT recorded_unix_ns FROM worker_registrations WHERE worker_id='worker-two'"
        ).fetchone()[0], fixture.now + 2)

    def test_envelope_and_lease_admission_recheck_expiry_after_lock(self):
        for path in ("envelope", "lease_expiry", "lease_envelope"):
            with self.subTest(path=path):
                fixture = self.fixture(product_fixtures.ProductClaimAdmissionTests)
                store = fixture.product.store
                anchor = store.audit_anchor()
                after = fixture.now + (1_000_001 if path == "lease_envelope" else 20)
                with self.advance_at_lock(store, fixture.now + 2, after):
                    if path == "envelope":
                        envelope = replace(fixture.envelope, envelope_id="new", expires_unix_ns=fixture.now + 10)
                        with self.assertRaisesRegex(EngineeringError, "expired_envelope"):
                            fixture.product.admit_repository_envelope(envelope)
                    else:
                        expiry = fixture.envelope.expires_unix_ns if path == "lease_envelope" else fixture.now + 10
                        with self.assertRaisesRegex(EngineeringError, "invalid_lease_expiry"):
                            fixture.product.acquire_lease(
                                "new", "env", "worker", ("src",),
                                authority_epoch=1, expires_unix_ns=expiry,
                            )
                self.assertEqual(store.audit_anchor(), anchor)

    def test_lease_renewal_cannot_revive_authority_expired_during_lock_wait(self):
        fixture = self.fixture(product_fixtures.ProductClaimAdmissionTests)
        lease = fixture.lease()
        store = fixture.product.store
        anchor = store.audit_anchor()
        with self.advance_at_lock(store, fixture.now + 2, fixture.now + 500_001):
            with self.assertRaisesRegex(EngineeringError, "stale_lease_revision|lease_not_active"):
                store.transition_path_lease(
                    "lease", expected_revision=lease.revision, authority_epoch=lease.epoch,
                    disposition="renew", new_expiry_unix_ns=fixture.now + 600_000,
                )
        self.assertEqual(store.audit_anchor(), anchor)

    def test_native_schedule_cannot_publish_after_envelope_expires_during_lock_wait(self):
        fixture = self.fixture(product_fixtures.ProductClaimAdmissionTests)
        store = fixture.product.store
        anchor = store.audit_anchor()
        with self.advance_at_lock(store, fixture.now + 2, fixture.envelope.expires_unix_ns + 1):
            with self.assertRaisesRegex(EngineeringError, "expired_envelope"):
                store.schedule_ready_packages(
                    "env", (WorkPackage(0, "job", (), ("src/job",)),), (), generation_id="native",
                )
        self.assertEqual(store.audit_anchor(), anchor)

    def test_signed_source_wrapper_preserves_default_time_until_owner_lock(self):
        fixture = self.fixture(orchestration_fixtures.OrchestrationTests)
        store = self.store()
        trust = HmacTrustStore({("source_authority", "source"): b"source"})
        source = CanonicalSourceReceipt(
            "acme/repository", "9" * 40, "8" * 40,
            fixture.envelope.source_commit, fixture.envelope.source_tree, "f" * 64,
            "source_authority", "source", fixture.now, fixture.now + 10,
        )
        source = replace(source, signature=trust.sign(source, source.issuer, source.signing_identity))
        envelope = replace(fixture.envelope, expires_unix_ns=source.expires_unix_ns)
        anchor = store.audit_anchor()
        with self.advance_at_lock(store, fixture.now + 2, fixture.now + 20):
            with self.assertRaisesRegex(EngineeringError, "source_receipt_stale"):
                issue_signed_work_envelope(
                    store, envelope, source, trust, expected_repository="acme/repository",
                    expected_document_set_digest="f" * 64,
                )
            self.assertEqual(store.audit_anchor(), anchor)
            self.assertEqual(issue_signed_work_envelope(
                store, envelope, source, trust, expected_repository="acme/repository",
                expected_document_set_digest="f" * 64, now_ns=fixture.now + 2,
            ), envelope)

    def test_planner_rechecks_completed_predecessor_window_at_locked_cut(self):
        fixture = self.fixture(orchestration_fixtures.OrchestrationTests)
        store = self.store()
        store.issue_work_envelope(fixture.envelope, now_ns=fixture.now)
        completion = fixture.completion(store, "predecessor", "src/predecessor")
        package = EngineeringWorkPackage(0, "dependent", ("predecessor",), ("src/dependent",))
        anchor = store.audit_anchor()
        with self.advance_at_lock(store, fixture.now + 2, completion.expires_unix_ns + 1):
            with self.assertRaisesRegex(EngineeringError, "completion_receipt_stale"):
                plan_engineering_work(
                    store, fixture.envelope, (package,), (WorkerProfile("worker", (), 1, ("src",)),),
                    (completion,), fixture.trust, EngineeringCapacity(1, ()), generation_id="dependent",
                )
            self.assertEqual(store.audit_anchor(), anchor)
            plan = plan_engineering_work(
                store, fixture.envelope, (package,), (WorkerProfile("worker", (), 1, ("src",)),),
                (completion,), fixture.trust, EngineeringCapacity(1, ()),
                generation_id="dependent", now_ns=fixture.now + 2,
            )
        self.assertEqual(plan.assignments[0].package_id, "dependent")

    def test_worker_heartbeat_result_and_completion_validate_at_locked_cut(self):
        for operation in ("heartbeat", "result", "completion"):
            with self.subTest(operation=operation):
                fixture = self.fixture(worker_fixtures.WorkerLifecycleTests)
                store = self.store()
                fixture.register(store)
                fixture.plan_and_lease(store)
                claim = claim_assignment(
                    store, "generation-a", "package-a", "worker-a", "lease-a",
                    heartbeat_ttl_ns=3_000_000_000, now_ns=fixture.now + 2,
                )
                if operation != "heartbeat":
                    claim = heartbeat_claim(
                        store, fixture.heartbeat(claim, fixture.now + 3), fixture.trust,
                        heartbeat_ttl_ns=3_000_000_000, now_ns=fixture.now + 3,
                    )
                if operation == "completion":
                    claim = submit_worker_result(
                        store, fixture.result(claim, fixture.now + 4, "success"),
                        fixture.trust, now_ns=fixture.now + 4,
                    )
                receipt = (
                    fixture.heartbeat(claim, fixture.now + 5) if operation == "heartbeat" else
                    fixture.result(claim, fixture.now + 5, "success") if operation == "result" else
                    fixture.completion(store, claim, fixture.now + 5)
                )
                anchor = store.audit_anchor()
                with self.advance_at_lock(store, fixture.now + 6, receipt.expires_unix_ns + 1):
                    expected = "worker_heartbeat_stale|claim_heartbeat_expired" if operation == "heartbeat" else (
                        "worker_result_stale|claim_heartbeat_expired" if operation == "result" else "completion_receipt_stale"
                    )
                    with self.assertRaisesRegex(EngineeringError, expected):
                        if operation == "heartbeat":
                            heartbeat_claim(store, receipt, fixture.trust, heartbeat_ttl_ns=3_000_000_000)
                        elif operation == "result":
                            submit_worker_result(store, receipt, fixture.trust)
                        else:
                            observe_claim_completion(store, claim.claim_id, fixture.envelope, receipt, fixture.trust)
                self.assertEqual(store.audit_anchor(), anchor)
                self.assertEqual(store.connection.execute(
                    "SELECT state,revision FROM worker_claims WHERE claim_id=?", (claim.claim_id,)
                ).fetchone()[:], (claim.state, claim.revision))

    def test_registration_renewal_window_is_locked_but_historical_ack_remains_replayable(self):
        fixture = self.fixture(product_fixtures.ProductClaimAdmissionTests)
        store = fixture.product.store
        row = store.connection.execute("SELECT * FROM worker_registrations WHERE worker_id='worker'").fetchone()
        receipt = WorkerRegistrationRenewalReceipt(
            "worker", int(row["revision"]), str(row["profile_digest"]), "worker-key",
            fixture.profile.skills, 5, fixture.profile.allowed_paths,
            "engineering_worker_identity", "identity-key", fixture.now + 3, fixture.envelope.expires_unix_ns,
        )
        receipt = replace(receipt, signature=fixture.trust.sign(receipt, receipt.issuer, receipt.signing_identity))
        anchor = store.audit_anchor()
        with self.advance_at_lock(store, fixture.now + 4, receipt.expires_unix_ns + 1):
            with self.assertRaisesRegex(EngineeringError, "signed_observation_stale"):
                fixture.product.renew_worker_registration(receipt)
            self.assertEqual(store.audit_anchor(), anchor)
            digest = fixture.product.renew_worker_registration(receipt, now_ns=fixture.now + 4)
            anchor = store.audit_anchor()
            self.assertEqual(fixture.product.renew_worker_registration(receipt), digest)
            self.assertEqual(store.audit_anchor(), anchor)

    def test_seal_eligible_decision_validates_window_after_owner_lock(self):
        fixture = self.fixture(seal_fixtures.SealedEvidenceBoundaryTests)
        store = self.store()
        sealed = fixture.sealed()
        anchor = store.audit_anchor()
        with self.advance_at_lock(store, fixture.now, sealed.expires_unix_ns + 1):
            with self.assertRaisesRegex(EngineeringError, "sealed_evidence_stale"):
                record_integration_decision(store, "decision", sealed, trust_store=fixture.trust)
            self.assertEqual(store.audit_anchor(), anchor)
            record_integration_decision(store, "decision", sealed, trust_store=fixture.trust, now_ns=fixture.now)
        self.assertEqual(store.connection.execute(
            "SELECT eligible,created_unix_ns FROM integration_decisions WHERE decision_id='decision'"
        ).fetchone()[:], (1, fixture.now))

    def test_integration_stage_and_terminal_receipts_recheck_window_after_lock(self):
        for operation in ("stage", "terminal"):
            with self.subTest(operation=operation):
                fixture = self.fixture(integration_fixtures.IntegrationControllerTests)
                store = self.store()
                fixture.publish(store)
                if operation == "terminal":
                    for index, stage in enumerate(("candidate", "review", "ci"), 1):
                        observe_integration_stage(
                            store, "queue-a", "package-a",
                            current_base_commit=fixture.base_commit, current_base_tree=fixture.base_tree,
                            receipt=fixture.stage_receipt(stage, str(index) * 64),
                            trust_store=fixture.trust, now_ns=fixture.now + 2,
                        )
                receipt = fixture.stage_receipt("candidate", "1" * 64) if operation == "stage" else fixture.terminal_receipt()
                anchor = store.audit_anchor()
                with self.advance_at_lock(store, fixture.now + 3, receipt.expires_unix_ns + 1):
                    expected = "integration_stage_receipt_binding" if operation == "stage" else "integration_terminal_receipt_binding"
                    with self.assertRaisesRegex(EngineeringError, expected):
                        if operation == "stage":
                            observe_integration_stage(
                                store, "queue-a", "package-a",
                                current_base_commit=fixture.base_commit, current_base_tree=fixture.base_tree,
                                receipt=receipt, trust_store=fixture.trust,
                            )
                        else:
                            reconcile_integration_item(
                                store, "queue-a", "package-a",
                                current_base_commit=fixture.base_commit, current_base_tree=fixture.base_tree,
                                terminal_receipt=receipt, trust_store=fixture.trust,
                            )
                self.assertEqual(store.audit_anchor(), anchor)


if __name__ == "__main__":
    unittest.main()
