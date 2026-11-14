from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from control_engineering_v2 import (
    EngineeringCapacity,
    EngineeringStore,
    EngineeringWorkPackage,
    HmacTrustStore,
    WorkerProfile,
    WorkerRegistrationReceipt,
    WorkEnvelope,
    claim_assignment,
    plan_engineering_work,
    register_worker,
)
from control_engineering_v2.control_plane import DENIED_AUTHORITIES
from control_engineering_v2.worker_registration import (
    WorkerRegistrationRenewalReceipt,
    renew_worker_registration,
)


class WorkerRegistrationRenewalTests(unittest.TestCase):
    def setUp(self):
        self.now = 1_000_000_000
        self.trust = HmacTrustStore(
            {("engineering_worker_identity", "authority-key"): b"authority"}
        )

    def initial(self):
        value = WorkerRegistrationReceipt(
            "worker-a",
            "worker-key-a",
            ("python",),
            2,
            ("src",),
            "engineering_worker_identity",
            "authority-key",
            self.now,
            self.now + 5_000_000_000,
        )
        return replace(
            value,
            signature=self.trust.sign(value, value.issuer, value.signing_identity),
        )

    def renewal(self, predecessor_digest, *, key="worker-key-a", expiry=None):
        value = WorkerRegistrationRenewalReceipt(
            "worker-a",
            1,
            predecessor_digest,
            "worker-key-a",
            key,
            ("python",),
            2,
            ("src",),
            "engineering_worker_identity",
            "authority-key",
            self.now + 1,
            expiry or self.now + 6_000_000_000,
        )
        return replace(
            value,
            signature=self.trust.sign(value, value.issuer, value.signing_identity),
        )

    def test_rotation_is_revision_bound_and_replay_stable(self):
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "engineering.sqlite3") as store:
                predecessor = register_worker(
                    store,
                    self.initial(),
                    self.trust,
                    now_ns=self.now,
                )
                renewal = self.renewal(predecessor, key="worker-key-b")
                digest = renew_worker_registration(
                    store,
                    renewal,
                    self.trust,
                    now_ns=self.now + 1,
                )
                row = store.connection.execute(
                    "SELECT * FROM worker_registrations WHERE worker_id='worker-a'"
                ).fetchone()
                self.assertEqual(int(row["revision"]), 2)
                self.assertEqual(str(row["worker_signing_identity"]), "worker-key-b")
                anchor = store.audit_anchor()
                self.assertEqual(
                    renew_worker_registration(
                        store,
                        renewal,
                        self.trust,
                        now_ns=self.now + 1,
                    ),
                    digest,
                )
                self.assertEqual(store.audit_anchor(), anchor)

    def test_profile_or_key_rotation_is_rejected_while_claim_is_active(self):
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "engineering.sqlite3") as store:
                predecessor = register_worker(
                    store,
                    self.initial(),
                    self.trust,
                    now_ns=self.now,
                )
                envelope = WorkEnvelope(
                    "env",
                    "a" * 40,
                    "b" * 40,
                    "c" * 64,
                    "d" * 64,
                    "developer-productivity",
                    ("src",),
                    tuple(sorted(DENIED_AUTHORITIES)),
                    1,
                    self.now + 4_000_000_000,
                )
                store.issue_work_envelope(envelope, now_ns=self.now)
                plan = plan_engineering_work(
                    store,
                    envelope,
                    (
                        EngineeringWorkPackage(
                            0,
                            "package-a",
                            (),
                            ("src/package-a",),
                            required_skills=("python",),
                            capacity_units=1,
                        ),
                    ),
                    (WorkerProfile("worker-a", ("python",), 2, ("src",)),),
                    (),
                    self.trust,
                    EngineeringCapacity(1, ()),
                    generation_id="generation-a",
                    now_ns=self.now,
                )
                store.acquire_path_lease(
                    "lease-a",
                    envelope.envelope_id,
                    "worker-a",
                    ("src/package-a",),
                    authority_epoch=1,
                    expires_unix_ns=self.now + 3_000_000_000,
                    now_ns=self.now + 1,
                )
                claim_assignment(
                    store,
                    plan.generation_id,
                    "package-a",
                    "worker-a",
                    "lease-a",
                    heartbeat_ttl_ns=1_000_000_000,
                    now_ns=self.now + 2,
                )
                with self.assertRaisesRegex(
                    ValueError,
                    "worker_registration_rotation_active_claims",
                ):
                    renew_worker_registration(
                        store,
                        self.renewal(predecessor, key="worker-key-b"),
                        self.trust,
                        now_ns=self.now + 3,
                    )
                # Expiry-only renewal may keep the already-admitted identity alive.
                renew_worker_registration(
                    store,
                    self.renewal(predecessor),
                    self.trust,
                    now_ns=self.now + 3,
                )

    def test_stale_predecessor_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "engineering.sqlite3") as store:
                register_worker(store, self.initial(), self.trust, now_ns=self.now)
                bad = self.renewal("f" * 64)
                with self.assertRaisesRegex(
                    ValueError,
                    "worker_registration_predecessor_mismatch",
                ):
                    renew_worker_registration(
                        store,
                        bad,
                        self.trust,
                        now_ns=self.now + 1,
                    )


if __name__ == "__main__":
    unittest.main()
