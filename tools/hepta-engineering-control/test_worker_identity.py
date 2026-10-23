from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from control_engineering_v2 import (
    EngineeringStore,
    HmacTrustStore,
    WorkerRegistrationReceipt,
    register_worker,
    semantic_digest,
)
from control_engineering_v2.control_plane import EngineeringError
from control_engineering_v2.worker_identity import (
    WorkerRegistrationRenewalReceipt,
    renew_worker_registration,
)


class WorkerIdentityRenewalTests(unittest.TestCase):
    def setUp(self):
        self.now = 1_000_000_000
        self.trust = HmacTrustStore(
            {("engineering_worker_identity", "authority-key"): b"authority"}
        )

    def _register(self, store):
        value = WorkerRegistrationReceipt(
            "worker-a",
            "worker-key-v1",
            ("python",),
            4,
            ("src",),
            "engineering_worker_identity",
            "authority-key",
            self.now,
            self.now + 3_600_000_000_000,
        )
        value = replace(
            value,
            signature=self.trust.sign(value, value.issuer, value.signing_identity),
        )
        return register_worker(store, value, self.trust, now_ns=self.now)

    def _renewal(
        self,
        previous_digest,
        *,
        expected_revision=1,
        new_key="worker-key-v1",
        reason="",
    ):
        value = WorkerRegistrationRenewalReceipt(
            "worker-a",
            expected_revision,
            previous_digest,
            "worker-key-v1" if expected_revision == 1 else "worker-key-v1",
            new_key,
            ("python", "sqlite"),
            6,
            ("src",),
            "engineering_worker_identity",
            "authority-key",
            self.now + expected_revision,
            self.now + 7_200_000_000_000,
            reason,
        )
        return replace(
            value,
            signature=self.trust.sign(value, value.issuer, value.signing_identity),
        )

    def test_renewal_is_revision_bound_and_ack_loss_stable(self):
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "engineering.sqlite3") as store:
                previous = self._register(store)
                receipt = self._renewal(previous)
                first = renew_worker_registration(
                    store, receipt, self.trust, now_ns=self.now + 1
                )
                replay = renew_worker_registration(
                    store, receipt, self.trust, now_ns=self.now + 2
                )
                self.assertEqual(first.revision, 2)
                self.assertFalse(first.replayed)
                self.assertTrue(replay.replayed)
                self.assertEqual(first.receipt_digest, replay.receipt_digest)
                row = store.connection.execute(
                    "SELECT revision,worker_signing_identity,capacity_units "
                    "FROM worker_registrations WHERE worker_id='worker-a'"
                ).fetchone()
                self.assertEqual(tuple(row), (2, "worker-key-v1", 6))

    def test_renewal_replay_survives_arbitrary_later_audit_growth_and_reopen(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "engineering.sqlite3"
            with EngineeringStore(database) as store:
                previous = self._register(store)
                receipt = self._renewal(previous)
                first = renew_worker_registration(
                    store, receipt, self.trust, now_ns=self.now + 1
                )
                with store._transaction():
                    for index in range(300):
                        store._append_audit(
                            "worker_identity_test_noise",
                            {"index": index},
                            self.now + 2 + index,
                        )
                self.assertGreater(store.audit_anchor()["sequence"], 256)

            with EngineeringStore(database) as reopened:
                replay = renew_worker_registration(
                    reopened,
                    receipt,
                    self.trust,
                    now_ns=self.now + 1_000,
                )
                self.assertTrue(replay.replayed)
                self.assertEqual(replay.receipt_digest, first.receipt_digest)
                self.assertEqual(replay.revision, 2)

    def test_key_rotation_requires_authority_signature_and_reason(self):
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "engineering.sqlite3") as store:
                previous = self._register(store)
                first = self._renewal(previous)
                decision = renew_worker_registration(
                    store, first, self.trust, now_ns=self.now + 1
                )
                rotated_profile = {
                    "workerId": "worker-a",
                    "workerSigningIdentity": "worker-key-v1",
                    "skills": ("python", "sqlite"),
                    "capacityUnits": 6,
                    "allowedPaths": ("src",),
                }
                self.assertEqual(
                    decision.profile_digest, semantic_digest(rotated_profile)
                )
                value = WorkerRegistrationRenewalReceipt(
                    "worker-a",
                    2,
                    decision.profile_digest,
                    "worker-key-v1",
                    "worker-key-v2",
                    ("python", "sqlite"),
                    6,
                    ("src",),
                    "engineering_worker_identity",
                    "authority-key",
                    self.now + 3,
                    self.now + 7_200_000_000_000,
                    "scheduled_rotation",
                )
                value = replace(
                    value,
                    signature=self.trust.sign(
                        value, value.issuer, value.signing_identity
                    ),
                )
                rotated = renew_worker_registration(
                    store, value, self.trust, now_ns=self.now + 3
                )
                self.assertTrue(rotated.key_rotated)
                self.assertEqual(rotated.revision, 3)

                bad = replace(value, expected_revision=3, signature="0" * 64)
                with self.assertRaisesRegex(
                    EngineeringError, "worker_renewal_signature"
                ):
                    renew_worker_registration(
                        store, bad, self.trust, now_ns=self.now + 4
                    )


if __name__ == "__main__":
    unittest.main()
