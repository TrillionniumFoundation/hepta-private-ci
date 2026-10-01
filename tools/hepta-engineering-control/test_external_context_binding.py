"""External proofs must describe the durable owner and one consistent read cut."""

from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from control_engineering_v2 import EngineeringError, EngineeringStore
from control_engineering_v2.external_controls import (
    AuditAnchorAttestation,
    admit_distributed_fence,
    store_snapshot_digest,
    verify_distributed_fence,
    verify_distributed_revocation_frontier,
    verify_external_audit_anchor,
    verify_persisted_distributed_fence,
    verify_production_controls,
)
from control_engineering_v2.worker_lifecycle import recover_worker_lifecycle
import test_external_controls as fixture_module
from control_engineering_v2.control_plane import canonical_json


class ExternalContextBindingTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.ExternalControlTests()
        self.fixture.setUp()
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.database = Path(self.temporary.name) / "owner.db"
        self.store = EngineeringStore(self.database)
        self.addCleanup(self.store.close)
        self.store.issue_work_envelope(self.fixture.envelope, now_ns=self.fixture.now)
        self.lease = self.store.acquire_path_lease(
            "lease", "env", "worker", ("src/a",), authority_epoch=1,
            expires_unix_ns=self.fixture.now + 500, now_ns=self.fixture.now,
        )
        self.frontier = self.fixture.frontier()
        self.fence = self.fixture.fence(self.lease, self.frontier)

    def audit(self, store=None, envelope=None):
        store = self.store if store is None else store
        envelope = self.fixture.envelope if envelope is None else envelope
        anchor = store.audit_anchor()
        return self.fixture.sign(AuditAnchorAttestation(
            sequence=anchor["sequence"], event_digest=anchor["eventDigest"],
            envelope_id=envelope.envelope_id, source_commit=envelope.source_commit,
            source_tree=envelope.source_tree, store_snapshot_digest=store_snapshot_digest(store),
            issuer="audit_anchor_service", signing_identity="audit-key",
            observed_unix_ns=self.fixture.now - 1,
            expires_unix_ns=self.fixture.now + 100,
        ))

    def admit(self, envelope=None, fence=None):
        return admit_distributed_fence(
            self.lease, self.fixture.envelope if envelope is None else envelope,
            self.fence if fence is None else fence, self.frontier, self.fixture.trust,
            store=self.store, now_ns=self.fixture.now,
        )

    def test_valid_owner_context_remains_admissible(self):
        self.assertEqual(len(self.admit()), 64)
        self.assertEqual(len(verify_external_audit_anchor(
            self.store, self.fixture.envelope, self.audit(), self.fixture.trust,
            now_ns=self.fixture.now,
        )), 64)

    def test_signed_persisted_frontier_scalars_reject_overflow_without_effects(self):
        for field in ("leader_term", "frontier_sequence"):
            for value in (2**63, True):
                with self.subTest(field=field, value=value):
                    frontier = self.fixture.sign(replace(
                        self.frontier, **{field: value}, signature="",
                    ))
                    fence = self.fixture.fence(self.lease, frontier)
                    before = tuple(self.store.connection.iterdump())
                    with self.assertRaisesRegex(EngineeringError, "distributed_revocation_frontier_order"):
                        admit_distributed_fence(
                            self.lease, self.fixture.envelope, fence, frontier,
                            self.fixture.trust, store=self.store, now_ns=self.fixture.now,
                        )
                    self.assertEqual(tuple(self.store.connection.iterdump()), before)

    def test_signed_fence_time_scalars_reject_invalid_windows_without_effects(self):
        frontier = self.fixture.frontier(expires_offset=2**80 - self.fixture.now)
        for field, value in (("observed_unix_ns", -1), ("expires_unix_ns", 2**63)):
            with self.subTest(field=field):
                fence = self.fixture.sign(replace(self.fence, **{field: value}, signature=""))
                before = tuple(self.store.connection.iterdump())
                with self.assertRaisesRegex(EngineeringError, "distributed_fence_stale"):
                    admit_distributed_fence(
                        self.lease, self.fixture.envelope, fence, frontier,
                        self.fixture.trust, store=self.store, now_ns=self.fixture.now,
                    )
                self.assertEqual(tuple(self.store.connection.iterdump()), before)

    def test_signed_frontier_negative_observation_is_not_a_valid_window(self):
        frontier = self.fixture.sign(replace(self.frontier, observed_unix_ns=-1, signature=""))
        before = tuple(self.store.connection.iterdump())
        with self.assertRaisesRegex(EngineeringError, "distributed_revocation_frontier_stale"):
            verify_distributed_revocation_frontier(
                frontier, self.fixture.trust, now_ns=self.fixture.now,
            )
        self.assertEqual(tuple(self.store.connection.iterdump()), before)

    def test_persisted_counter_maximum_and_json_only_expiry_remain_admissible(self):
        maximum = 2**63 - 1
        frontier = self.fixture.frontier(
            sequence=maximum, leader_term=maximum, expires_offset=2**80 - self.fixture.now,
        )
        fence = self.fixture.fence(self.lease, frontier)
        digest = admit_distributed_fence(
            self.lease, self.fixture.envelope, fence, frontier, self.fixture.trust,
            store=self.store, now_ns=self.fixture.now,
        )
        for table in ("distributed_cluster_frontiers", "distributed_fence_frontiers"):
            row = self.store.connection.execute(
                f"SELECT leader_term,revocation_frontier_sequence FROM {table}"
            ).fetchone()
            self.assertEqual(tuple(row), (maximum, maximum))
        before = tuple(self.store.connection.iterdump())
        self.assertEqual(admit_distributed_fence(
            self.lease, self.fixture.envelope, fence, frontier, self.fixture.trust,
            store=self.store, now_ns=self.fixture.now,
        ), digest)
        self.assertEqual(tuple(self.store.connection.iterdump()), before)

    def test_signed_foreign_envelope_semantics_cannot_override_registered_owner(self):
        original = self.fixture.envelope
        variants = {
            "source_commit": "e" * 40, "source_tree": "f" * 40,
            "owner": "other-owner", "objective_digest": "e" * 64,
            "contract_digest": "f" * 64, "allowed_paths": ("other",),
            "maximum_assignments": 1, "revision": 99,
            "expires_unix_ns": self.fixture.now + 2000,
        }
        for field, value in variants.items():
            foreign = replace(original, **{field: value})
            self.fixture.envelope = foreign
            fence = self.fixture.fence(self.lease, self.frontier)
            with self.subTest(field=field, boundary="fence"):
                with self.store._transaction():
                    with self.assertRaisesRegex(EngineeringError, "distributed_fence_envelope_mismatch"):
                        self.admit(envelope=foreign, fence=fence)
            with self.subTest(field=field, boundary="audit"):
                with self.assertRaisesRegex(EngineeringError, "audit_anchor_binding_mismatch"):
                    verify_external_audit_anchor(
                        self.store, foreign, self.audit(envelope=foreign), self.fixture.trust,
                        now_ns=self.fixture.now,
                    )
        self.fixture.envelope = original
        self.assertEqual(self.store.connection.execute(
            "SELECT COUNT(*) FROM distributed_fence_frontiers"
        ).fetchone()[0], 0)

    def test_boolean_counters_do_not_bind_integer_lease_identity(self):
        for field in ("authority_epoch", "fencing_token", "lease_revision", "envelope_revision"):
            with self.subTest(field=field):
                signed = self.fixture.sign(replace(self.fence, **{field: True}, signature=""))
                with self.assertRaisesRegex(EngineeringError, "distributed_fence_order"):
                    verify_distributed_fence(
                        self.lease, self.fixture.envelope, signed, self.frontier,
                        self.fixture.trust, store=self.store, now_ns=self.fixture.now,
                    )

    def test_fractional_durable_owner_counters_cannot_match_integer_proofs(self):
        self.admit()
        tables = {
            "work_envelopes": ("maximum_assignments", "revision", "expires_unix_ns"),
            "path_leases": ("authority_epoch", "fencing_token", "revision", "expires_unix_ns"),
            "distributed_cluster_frontiers": ("leader_term", "revocation_frontier_sequence"),
            "distributed_fence_frontiers": ("leader_term", "revocation_frontier_sequence",
                                            "authority_epoch", "fencing_token", "lease_revision"),
        }
        for table, fields in tables.items():
            for field in fields:
                with self.subTest(table=table, field=field):
                    original = self.store.connection.execute(
                        f"SELECT {field} FROM {table}"
                    ).fetchone()[0]
                    self.store.connection.execute(f"UPDATE {table} SET {field}=?", (original + 0.5,))
                    self.store.connection.commit()
                    try:
                        with self.assertRaises(EngineeringError):
                            verify_persisted_distributed_fence(
                                self.lease, self.fixture.envelope, self.fence, self.frontier,
                                self.fixture.trust, store=self.store, now_ns=self.fixture.now,
                            )
                        with self.assertRaises(EngineeringError):
                            self.admit()
                    finally:
                        self.store.connection.execute(f"UPDATE {table} SET {field}=?", (original,))
                        self.store.connection.commit()

    def test_blob_owner_cannot_match_text_through_string_coercion(self):
        envelope = replace(self.fixture.envelope, envelope_id="blob-env", owner="b'owner'")
        self.store.issue_work_envelope(envelope, now_ns=self.fixture.now)
        lease = self.store.acquire_path_lease(
            "blob-lease", envelope.envelope_id, "blob-worker", ("src/b",), authority_epoch=1,
            expires_unix_ns=self.fixture.now + 500, now_ns=self.fixture.now,
        )
        self.fixture.envelope = envelope
        fence = self.fixture.fence(lease, self.frontier)
        self.store.connection.execute(
            "UPDATE work_envelopes SET owner=? WHERE envelope_id=?",
            (b"owner", envelope.envelope_id),
        )
        self.store.connection.commit()
        with self.assertRaisesRegex(EngineeringError, "distributed_fence_envelope_mismatch"):
            admit_distributed_fence(
                lease, envelope, fence, self.frontier, self.fixture.trust,
                store=self.store, now_ns=self.fixture.now,
            )

    def test_json_object_keys_cannot_match_durable_lease_paths(self):
        self.store.connection.execute(
            "UPDATE path_leases SET paths_json=? WHERE lease_id=?",
            (canonical_json({"src/a": "foreign-data"}), self.lease.lease_id),
        )
        self.store.connection.commit()
        with self.assertRaisesRegex(EngineeringError, "distributed_fence_local_lease_invalid"):
            self.admit()

    def test_production_controls_reject_fence_and_audit_from_different_owner_cuts(self):
        self.admit()
        replica_path = Path(self.temporary.name) / "audit-replica.db"
        replica_connection = sqlite3.connect(replica_path)
        self.store.connection.backup(replica_connection)
        replica_connection.close()
        with EngineeringStore(replica_path) as replica:
            replica.transition_path_lease(
                self.lease.lease_id, expected_revision=self.lease.revision,
                authority_epoch=self.lease.epoch, disposition="release", now_ns=self.fixture.now,
            )
            post_release_audit = self.audit(store=replica)
        original_transaction = self.store._transaction
        releases = []

        @contextmanager
        def release_after_owner_cut():
            with original_transaction():
                yield
            if not self.store.connection.in_transaction and not releases:
                with EngineeringStore(self.database) as second_owner:
                    second_owner.transition_path_lease(
                        self.lease.lease_id, expected_revision=self.lease.revision,
                        authority_epoch=self.lease.epoch, disposition="release",
                        now_ns=self.fixture.now,
                    )
                releases.append(True)
                self.assertEqual(store_snapshot_digest(self.store),
                                 post_release_audit.store_snapshot_digest)

        with mock.patch.object(self.store, "_transaction", release_after_owner_cut):
            with self.assertRaisesRegex(EngineeringError, "audit_anchor_binding_mismatch"):
                verify_production_controls(
                    self.lease, self.fixture.envelope, self.fence, self.frontier, self.store,
                    post_release_audit, self.fixture.custody_set(), self.fixture.trust,
                    now_ns=self.fixture.now,
                )
        self.assertEqual(self.store.connection.execute(
            "SELECT state,revision FROM path_leases WHERE lease_id=?", (self.lease.lease_id,)
        ).fetchone()[:], ("active", 1))

    def test_production_control_windows_use_one_observation_time(self):
        self.admit()
        audit = self.audit()
        custody = self.fixture.custody_set()
        with mock.patch("control_engineering_v2.external_controls.time.time_ns",
                        side_effect=(self.fixture.now, self.fixture.now + 1000)):
            decision = verify_production_controls(
                self.lease, self.fixture.envelope, self.fence, self.frontier, self.store,
                audit, custody, self.fixture.trust,
            )
        self.assertTrue(decision.external_audit_anchor_verified)

    def test_second_connection_reconciliation_cannot_change_owner_during_audit_verification(self):
        self.admit()
        audit = self.audit()
        custody = self.fixture.custody_set()
        blocked_reconciliations = []

        def snapshot_then_reconcile(store):
            digest = store_snapshot_digest(store)
            with EngineeringStore(self.database) as second_owner:
                second_owner.connection.execute("PRAGMA busy_timeout=0")
                try:
                    recover_worker_lifecycle(
                        second_owner, now_ns=self.lease.expires_unix_ns,
                    )
                except sqlite3.OperationalError as error:
                    if "database is locked" not in str(error):
                        raise
                    blocked_reconciliations.append(True)
            return digest

        with mock.patch("control_engineering_v2.external_controls.store_snapshot_digest",
                        side_effect=snapshot_then_reconcile):
            decision = verify_production_controls(
                self.lease, self.fixture.envelope, self.fence, self.frontier, self.store,
                audit, custody, self.fixture.trust, now_ns=self.fixture.now,
            )
        self.assertTrue(decision.external_audit_anchor_verified)
        self.assertEqual(blocked_reconciliations, [True])
        self.assertEqual(self.store.connection.execute(
            "SELECT state,revision FROM path_leases WHERE lease_id=?", (self.lease.lease_id,)
        ).fetchone()[:], ("active", 1))

    def test_lazy_custody_preparation_cannot_freeze_pre_expiry_observation_time(self):
        self.admit()
        audit = self.audit()
        custody = self.fixture.custody_set()
        clock = [self.fixture.now]

        def delayed_custody():
            clock[0] = self.fixture.now + 101
            yield from custody

        with mock.patch("control_engineering_v2.external_controls.time.time_ns",
                        side_effect=lambda: clock[0]):
            with self.assertRaisesRegex(EngineeringError, "distributed_fence_stale"):
                verify_production_controls(
                    self.lease, self.fixture.envelope, self.fence, self.frontier, self.store,
                    audit, delayed_custody(), self.fixture.trust,
                )

    def test_owner_lock_delay_cannot_freeze_pre_expiry_observation_time(self):
        self.admit()
        original_transaction = self.store._transaction
        clock = [self.fixture.now]

        @contextmanager
        def delayed_owner_cut():
            with original_transaction():
                clock[0] = self.fixture.now + 101
                yield

        for verify in (admit_distributed_fence, verify_persisted_distributed_fence):
            clock[0] = self.fixture.now
            with self.subTest(verify=verify.__name__):
                with mock.patch.object(self.store, "_transaction", delayed_owner_cut), mock.patch(
                    "control_engineering_v2.external_controls.time.time_ns", side_effect=lambda: clock[0]
                ):
                    with self.assertRaisesRegex(EngineeringError, "distributed_fence_stale"):
                        verify(
                            self.lease, self.fixture.envelope, self.fence, self.frontier,
                            self.fixture.trust, store=self.store,
                        )


if __name__ == "__main__":
    unittest.main()
