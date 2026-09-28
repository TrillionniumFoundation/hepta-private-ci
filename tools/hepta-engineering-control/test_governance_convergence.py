from dataclasses import asdict, replace
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from control_engineering_v2.audit_checkpoint import (
    build_audit_checkpoint,
    verify_audit_checkpoint,
)
from control_engineering_v2.capacity_policy import (
    EngineeringCapacityPolicy,
    EngineeringCapacitySnapshot,
    evaluate_engineering_capacity,
)
from control_engineering_v2.clock_policy import validate_receipt_window
from control_engineering_v2.control_plane import (
    DENIED_AUTHORITIES,
    EngineeringStore,
    WorkEnvelope,
    semantic_digest,
)
from control_engineering_v2.durability_soak import run_durability_soak
from control_engineering_v2.evidence import HmacTrustStore
from control_engineering_v2.worker_lifecycle import (
    WorkerRegistrationReceipt,
    register_worker,
)
from control_engineering_v2.worker_registration_governance import (
    WorkerRegistrationRotationReceipt,
    rotate_worker_registration,
)


class GovernanceConvergenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = 1_000_000_000
        self.source = "a" * 40
        self.tree = "b" * 40
        self.trust = HmacTrustStore(
            {("engineering_worker_identity", "identity-key"): b"identity"}
        )

    def sign(self, value):
        return replace(
            value,
            signature=self.trust.sign(value, value.issuer, value.signing_identity),
        )

    def envelope(self) -> WorkEnvelope:
        return WorkEnvelope(
            "env",
            self.source,
            self.tree,
            "c" * 64,
            "d" * 64,
            "developer-productivity",
            ("src",),
            tuple(sorted(DENIED_AUTHORITIES)),
            4,
            self.now + 20_000_000_000,
        )

    def register(self, store: EngineeringStore) -> str:
        receipt = WorkerRegistrationReceipt(
            "worker-a",
            "worker-key-v1",
            ("python",),
            4,
            ("src",),
            "engineering_worker_identity",
            "identity-key",
            self.now - 1,
            self.now + 4_000_000_000,
        )
        return register_worker(store, self.sign(receipt), self.trust, now_ns=self.now)

    def test_clock_skew_policy_accepts_current_and_rejects_future_or_stale(self):
        window = validate_receipt_window(
            self.now - 1,
            self.now + 1_000_000,
            now_ns=self.now,
        )
        self.assertEqual(window.future_skew_ns, 0)
        with self.assertRaisesRegex(ValueError, "receipt_observed_in_future"):
            validate_receipt_window(
                self.now + 6_000_000_000,
                self.now + 7_000_000_000,
                now_ns=self.now,
            )
        with self.assertRaisesRegex(ValueError, "receipt_observation_stale"):
            validate_receipt_window(
                self.now - 301_000_000_000,
                self.now + 1_000_000,
                now_ns=self.now,
            )

    def test_worker_registration_renewal_and_key_rotation_are_revision_bound(self):
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "engineering.sqlite3") as store:
                predecessor = self.register(store)
                renewal = self.sign(
                    WorkerRegistrationRotationReceipt(
                        "worker-a",
                        1,
                        predecessor,
                        "worker-key-v1",
                        ("python",),
                        4,
                        ("src",),
                        "renewal",
                        "engineering_worker_identity",
                        "identity-key",
                        self.now,
                        self.now + 8_000_000_000,
                    )
                )
                digest = rotate_worker_registration(
                    store, renewal, self.trust, now_ns=self.now
                )
                anchor = store.audit_anchor()
                self.assertEqual(
                    rotate_worker_registration(
                        store, renewal, self.trust, now_ns=self.now
                    ),
                    digest,
                )
                self.assertEqual(store.audit_anchor(), anchor)

                rotation = self.sign(
                    WorkerRegistrationRotationReceipt(
                        "worker-a",
                        2,
                        digest,
                        "worker-key-v2",
                        ("python", "sqlite"),
                        6,
                        ("src",),
                        "composite",
                        "engineering_worker_identity",
                        "identity-key",
                        self.now + 1,
                        self.now + 9_000_000_000,
                    )
                )
                rotated = rotate_worker_registration(
                    store, rotation, self.trust, now_ns=self.now + 1
                )
                row = store.connection.execute(
                    "SELECT revision,worker_signing_identity,capacity_units,profile_digest "
                    "FROM worker_registrations WHERE worker_id='worker-a'"
                ).fetchone()
                self.assertEqual(int(row["revision"]), 3)
                self.assertEqual(str(row["worker_signing_identity"]), "worker-key-v2")
                self.assertEqual(int(row["capacity_units"]), 6)
                self.assertEqual(str(row["profile_digest"]), rotated)

    def test_incremental_checkpoints_bind_delta_and_owner_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "engineering.sqlite3") as store:
                store.issue_work_envelope(self.envelope(), now_ns=self.now)
                first = build_audit_checkpoint(
                    store,
                    source_commit=self.source,
                    source_tree=self.tree,
                    now_ns=self.now + 1,
                )
                verify_audit_checkpoint(store, first)
                store.acquire_path_lease(
                    "lease-a",
                    "env",
                    "worker-a",
                    ("src/a",),
                    authority_epoch=1,
                    expires_unix_ns=self.now + 10_000_000_000,
                    now_ns=self.now + 2,
                )
                second = build_audit_checkpoint(
                    store,
                    source_commit=self.source,
                    source_tree=self.tree,
                    previous=first,
                    now_ns=self.now + 3,
                )
                self.assertEqual(second.predecessor_checkpoint_digest, first.checkpoint_digest)
                self.assertEqual(second.delta_event_count, 1)
                verify_audit_checkpoint(store, second)
                tampered = replace(second, owner_snapshot_digest="f" * 64)
                body = asdict(tampered)
                body.pop("checkpoint_digest")
                tampered = replace(tampered, checkpoint_digest=semantic_digest(body))
                with self.assertRaisesRegex(
                    ValueError, "audit_checkpoint_owner_snapshot_mismatch"
                ):
                    verify_audit_checkpoint(store, tampered)

    def test_capacity_policy_exposes_migration_threshold_and_hard_limit(self):
        policy = EngineeringCapacityPolicy(
            maximum_database_bytes=100,
            maximum_wal_bytes=100,
            maximum_audit_events=100,
            maximum_active_claims=100,
            maximum_active_reservations=100,
            migration_trigger_ratio_q16=52_429,
        )
        warning = evaluate_engineering_capacity(
            EngineeringCapacitySnapshot(80, 0, 0, 0, 0, 1, 4096, self.now),
            policy,
        )
        self.assertEqual(warning.state, "migration_required")
        blocked = evaluate_engineering_capacity(
            EngineeringCapacitySnapshot(101, 0, 0, 0, 0, 1, 4096, self.now),
            policy,
        )
        self.assertEqual(blocked.state, "blocked")

    def test_repeated_reopen_soak_retains_integrity(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "engineering.sqlite3"
            with EngineeringStore(path) as store:
                store.issue_work_envelope(self.envelope(), now_ns=self.now)
            report = run_durability_soak(path, iterations=5)
            self.assertTrue(report.quick_check_passed)
            self.assertTrue(report.foreign_key_check_passed)
            self.assertEqual(report.iterations, 5)
            self.assertNotEqual(report.report_digest, "0" * 64)

    def test_uncommitted_child_mutation_is_absent_after_crash(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "engineering.sqlite3"
            with EngineeringStore(path):
                pass
            code = f'''
import os
from control_engineering_v2.control_plane import DENIED_AUTHORITIES, EngineeringStore, WorkEnvelope
store = EngineeringStore({str(path)!r})
store.connection.execute("BEGIN IMMEDIATE")
store.issue_work_envelope(WorkEnvelope("crash-env", {self.source!r}, {self.tree!r}, "c"*64, "d"*64, "developer-productivity", ("src",), tuple(sorted(DENIED_AUTHORITIES)), 1, {self.now + 20_000_000_000}), now_ns={self.now})
os._exit(19)
'''
            result = subprocess.run(
                [sys.executable, "-c", code],
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                check=False,
            )
            self.assertEqual(result.returncode, 19)
            with EngineeringStore(path) as reopened:
                self.assertEqual(
                    reopened.connection.execute(
                        "SELECT COUNT(*) FROM work_envelopes "
                        "WHERE envelope_id='crash-env'"
                    ).fetchone()[0],
                    0,
                )
                reopened.verify_audit_chain()


if __name__ == "__main__":
    unittest.main()
